"""Scan the inbox for replies and bounces from contacted leads.

- Unsubscribe-style replies -> suppression.txt + status "unsubscribed"
- Bounces -> suppression.txt + status "bounced"
- Any other reply -> status "replied" (listed in the output so you can follow up personally)

Usage: python3 check_replies.py
"""
import email
import re
from email.header import decode_header, make_header
from email.utils import parseaddr

from common import (
    DATA, LEADS_FILE, add_suppression, connect_imap, load_env, read_json, single_instance, write_json,
)

SEEN_FILE = DATA / "replies_seen.json"
OPT_OUT = re.compile(r"\b(unsubscribe|remove me|take me off|stop emailing|do not (contact|email)|not interested|opt.?out)\b", re.I)
BOUNCE_SENDERS = ("mailer-daemon", "postmaster")


def text_of(msg):
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", "replace")
    return ""


def main():
    load_env()
    _lock = single_instance()
    leads = read_json(LEADS_FILE, {})
    contacted = {lead["email"].lower(): lead for lead in leads.values() if lead.get("sent_on")}
    if not contacted:
        print("No sent emails yet; nothing to check.")
        return
    seen = set(read_json(SEEN_FILE, []))
    since = min(lead["sent_on"] for lead in contacted.values())
    since_imap = __import__("datetime").date.fromisoformat(since).strftime("%d-%b-%Y")

    imap = connect_imap()
    imap.select("INBOX", readonly=True)  # read-only: doesn't mark anything as read
    _, data = imap.uid("search", None, f"SINCE {since_imap}")
    replies, opt_outs, bounces = [], [], []

    for uid in data[0].split():
        uid = uid.decode()
        if uid in seen:
            continue
        _, fetched = imap.uid("fetch", uid, "(BODY.PEEK[])")
        msg = email.message_from_bytes(fetched[0][1])
        sender = parseaddr(msg.get("From", ""))[1].lower()
        subject = str(make_header(decode_header(msg.get("Subject", ""))))
        body = text_of(msg)
        seen.add(uid)

        if sender.split("@")[0] in BOUNCE_SENDERS:
            raw = msg.as_string().lower()
            for addr, lead in contacted.items():
                if addr in raw and lead["status"] != "bounced":
                    lead["status"] = "bounced"
                    add_suppression(addr, "bounced")
                    bounces.append(addr)
            continue

        lead = contacted.get(sender)
        if not lead or lead["status"] in ("unsubscribed", "bounced"):
            continue
        # Only look at the reply's own text, not the quoted original (which contains our footer).
        own_text = re.split(r"\n\s*(>|On .+wrote:)", body, maxsplit=1)[0]
        if OPT_OUT.search(subject) or OPT_OUT.search(own_text):
            lead["status"] = "unsubscribed"
            add_suppression(sender, "asked to unsubscribe")
            opt_outs.append(sender)
        else:
            lead["status"] = "replied"
            replies.append(f"{lead['name']} <{sender}>: {subject}")

    imap.logout()
    write_json(LEADS_FILE, leads)
    write_json(SEEN_FILE, sorted(seen))
    print(f"Replies needing you: {len(replies)}")
    for r in replies:
        print(f"  {r}")
    print(f"Unsubscribed (suppressed): {len(opt_outs)} {', '.join(opt_outs)}")
    print(f"Bounced (suppressed): {len(bounces)} {', '.join(bounces)}")


if __name__ == "__main__":
    main()
