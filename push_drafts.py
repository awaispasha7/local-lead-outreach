"""Send (auto_send: true) or upload as mailbox drafts (auto_send: false) the emails Claude wrote.

Usage:
  python3 push_drafts.py                 # send / draft every data/drafts/*.json (sending respects max_sends_per_day)
  python3 push_drafts.py --dry-run       # print what would happen
  python3 push_drafts.py --list-folders  # show IMAP folder names (to set DRAFTS_FOLDER / SENT_FOLDER)
"""
import imaplib
import json
import os
import random
import smtplib
import sys
import time
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from common import (
    DRAFTS_DIR, LEADS_FILE, QUEUE_FILE, connect_imap, is_suppressed, load_config, load_env,
    read_json, require_env, single_instance, suppressed, write_json,
)


def footer(sender):
    # Added here rather than by Claude so every email carries the CAN-SPAM essentials.
    title = f"{sender['title']}, " if sender.get("title") else ""
    return (
        f"\n\nBest,\n{sender['name']}\n{title}{sender['company']} · {sender['website']}\n\n--\n"
        f"{sender['postal_address']}\n"
        'Not interested? Reply "unsubscribe" and I won\'t email you again.'
    )


def build_message(draft, sender, from_addr):
    msg = EmailMessage()
    msg["From"] = formataddr((sender["name"], from_addr))
    msg["To"] = draft["to"]
    msg["Subject"] = draft["subject"]
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[1])
    msg.set_content(draft["body"].rstrip() + footer(sender))
    return msg


def send_smtp(msg, from_addr):
    # A fresh connection per email: many providers drop SMTP sessions left idle during the pauses between sends.
    with smtplib.SMTP_SSL(require_env("SMTP_HOST"),
                          int(os.environ.get("SMTP_PORT", "465")), timeout=60) as smtp:
        smtp.login(from_addr, require_env("EMAIL_PASSWORD"))
        smtp.send_message(msg)


def main():
    load_env()
    _lock = single_instance()
    if "--list-folders" in sys.argv:
        imap = connect_imap()
        for folder in imap.list()[1]:
            print(folder.decode())
        imap.logout()
        return

    dry_run = "--dry-run" in sys.argv
    config = load_config()
    sender = config["sender"]
    auto_send = config.get("auto_send", False)
    from_addr = os.environ.get("EMAIL_ADDRESS", "you@example.com") if dry_run else require_env("EMAIL_ADDRESS")
    if not dry_run and "Example St" in sender["postal_address"]:
        raise SystemExit("Set a real sender.postal_address in config.yaml before sending (required by CAN-SPAM).")
    drafts_folder = os.environ.get("DRAFTS_FOLDER", "Drafts")
    sent_folder = os.environ.get("SENT_FOLDER", "Sent")
    blocked = suppressed()
    leads = read_json(LEADS_FILE, {})
    queue = read_json(QUEUE_FILE, [])
    done_dir = DRAFTS_DIR / "done"
    done_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    sent_today = sum(1 for lead in leads.values() if lead.get("sent_on") == today)
    budget = max(0, config.get("max_sends_per_day", 10) - sent_today) if auto_send else None
    delay_min, delay_max = config.get("send_delay_seconds", [30, 60])

    files = sorted(DRAFTS_DIR.glob("*.json"))
    if not files:
        print("No emails waiting in data/drafts/.")
        return
    imap = None
    if not dry_run:
        imap = connect_imap()
    handled, count = [], 0

    for path in files:
        draft = json.loads(path.read_text())
        lead_id = draft.get("lead_id")
        lead = leads.get(lead_id, {})
        if is_suppressed(draft["to"], blocked) or lead.get("status") in ("sent", "replied", "unsubscribed", "bounced"):
            print(f"Skipping {draft['to']} (suppressed or already contacted)")
            if not dry_run:
                path.rename(done_dir / path.name)
                if lead and lead.get("status") not in ("sent", "replied", "unsubscribed", "bounced"):
                    lead["status"] = "skipped"
                handled.append(lead_id)
            continue
        if auto_send and count >= budget:
            print(f"Daily cap reached ({config.get('max_sends_per_day', 10)}/day); "
                  f"{len(files) - files.index(path)} emails wait for the next run.")
            break

        msg = build_message(draft, sender, from_addr)
        if dry_run:
            print(f"--- {'SEND' if auto_send else 'DRAFT'} {draft['to']} | {draft['subject']}\n{msg.get_content()}\n")
            count += 1
            continue

        if auto_send:
            if count:
                time.sleep(random.uniform(delay_min, delay_max))  # pace sends so they don't go out as a burst
            try:
                send_smtp(msg, from_addr)
            except smtplib.SMTPException as exc:
                print(f"Send to {draft['to']} failed ({exc.__class__.__name__}: {exc}). "
                      "Stopping; the rest wait for the next run.")
                break
            # Many SMTP servers don't keep a copy, so file one in Sent for the record and for reply threading.
            imap.append(sent_folder, r"(\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            if lead:
                lead.update(status="sent", sent_on=today, message_id=msg["Message-ID"])
            print(f"Sent: {draft['to']} | {draft['subject']}")
        else:
            imap.append(drafts_folder, r"(\Draft \Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            if lead:
                lead["status"] = "drafted"
            print(f"Drafted: {draft['to']} | {draft['subject']}")
        path.rename(done_dir / path.name)
        handled.append(lead_id)
        count += 1
        write_json(LEADS_FILE, leads)

    if not dry_run:
        imap.logout()
        write_json(LEADS_FILE, leads)
        write_json(QUEUE_FILE, [lead for lead in queue if lead["id"] not in handled])
        where = "sent" if auto_send else f"in your '{drafts_folder}' mailbox folder"
        print(f"\n{count} emails {where}. {len(list(DRAFTS_DIR.glob('*.json')))} still waiting.")


if __name__ == "__main__":
    main()
