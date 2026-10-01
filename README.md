# local-lead-outreach

Find local businesses on Google, write each one a personalized cold email with Claude, and draft or send it from your own mailbox.

- **No LLM API key.** The writing step runs inside [Claude Code](https://claude.com/claude-code), on your existing Claude subscription.
- **Real personalization.** Each email is built from the business's own Google data: rating, review count, years in business, hours and badges.
- **Human-in-the-loop by default.** Emails land in your Drafts folder. Turn on `auto_send` when you trust the output.
- **Compliance built in.** Every email gets a CAN-SPAM footer, unsubscribe replies are honored automatically, bounces are suppressed, and sending is capped and paced.

```
check_replies.py   IMAP inbox → replies / unsubscribes / bounces → suppression.txt
leads.py           SerpAPI (Google Local Services Ads or Maps) → website → contact email → data/queue.json
Claude Code        follows WRITE_EMAILS.md → one personalized email per lead → data/drafts/*.json
push_drafts.py     IMAP Drafts folder (review mode) or SMTP send (auto mode), with a compliant footer
```

## Requirements
- Python 3.10+
- A [SerpAPI](https://serpapi.com) key (the free tier works for testing)
- A mailbox with IMAP and SMTP access (Hostinger, Zoho, Gmail with an app password, and so on)
- Claude Code with a Claude subscription

## Setup
```bash
git clone <this repo> && cd local-lead-outreach
pip install -r requirements.txt
cp .env.example .env                    # SerpAPI key + mailbox login
cp config.example.yaml config.yaml      # niches, cities, your sender details and offer
python3 push_drafts.py --list-folders   # find your Drafts / Sent folder names, put them in .env
```

## Run
Open the folder in Claude Code and run **`/outreach`**, or say "follow WRITE_EMAILS.md".

To run it every day, create a scheduled task in Claude Code (desktop app → Scheduled) with the prompt
"Follow WRITE_EMAILS.md in <path to this folder>". Use the cron that `python3 schedule.py` prints.

Useful flags:
- `python3 push_drafts.py --dry-run` previews every email without drafting or sending.
- `python3 leads.py --force` runs past the `runs_per_day` limit.

## Your data stays local
`.env`, `config.yaml`, `suppression.txt` and `data/` (leads, emails, sent history) are all gitignored.
Nothing is sent anywhere except SerpAPI (searches) and your own mail server.

## Cold email responsibly
- **Law:** in the US, CAN-SPAM requires a real postal address, a working opt-out and honest subject lines.
  The footer and `check_replies.py` handle the first two. Other countries are stricter: the EU/UK (GDPR, PECR)
  and Canada (CASL) may require prior consent. You are responsible for complying where your recipients are.
- **Deliverability:** use a separate outreach domain or mailbox, set up SPF, DKIM and DMARC,
  start at 10–20 emails a day and increase slowly. Many hosts suspend mailboxes that get spam complaints.
- **Terms:** respect SerpAPI's and your email provider's terms of service.

## Tips
- Local Services niches must be valid category keys (`plumber`, `hvac`, `roofer`, `general_contractor` and so on).
  See the [full list](https://serpapi.com/google-local-services-queries.json).
- Big franchises rarely list an email address on their website; independent shops usually do.
- Edit the "How to write each email" section of `WRITE_EMAILS.md` to change tone and structure.

## License
MIT
