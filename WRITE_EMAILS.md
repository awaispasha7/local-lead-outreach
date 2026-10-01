# Outreach run (instructions for Claude Code)

Work in this repository's folder. Run these steps in order:

1. `python3 check_replies.py`. It records replies and bounces, and puts unsubscribes and bounces
   into `suppression.txt`. Keep its output for the report.
2. `python3 leads.py` to find new leads and queue the ones with an email. If it reports that
   today's `runs_per_day` limit is reached, skip to step 4 (emails may still be waiting to send).
3. Read `config.yaml` (sender, offer, call_to_action) and `data/queue.json`.
   For every lead in the queue that has no file yet in `data/drafts/` or `data/drafts/done/`,
   write `data/drafts/<lead id>.json`:
   ```json
   {"lead_id": "...", "to": "<lead email>", "subject": "...", "body": "..."}
   ```
4. `python3 push_drafts.py` with a 10-minute timeout. With `auto_send: true` it sends up to
   `max_sends_per_day`, pausing between sends. With `auto_send: false` it only creates drafts.
   Never send email any other way, and never bypass the cap or `suppression.txt`.
5. Report: leads found, how many had emails, how many were sent or drafted, how many are still waiting,
   unsubscribes and bounces, and every reply that needs a personal response (name each one).

Never print values from `.env`.

## How to write each email

- Plain text, 60–110 words, no links in the body, no images, no markdown.
- Open with something specific to the business: their trade, city, rating or review count,
  years in business, weekly hours, or their Google badge. Never invent facts that aren't in the lead data.
  Use `hours.week`, not `hours.currently`, which only describes the moment of the search.
- Connect one real problem the business likely has to the `offer` in `config.yaml`, then end with the `call_to_action`.
- Subject: short, specific, no clickbait, no "Re:" or "Fwd:".
- Greeting "Hi <business name> team," unless an owner name is in the data.
- Don't add a sign-off, signature, address or unsubscribe line. `push_drafts.py` appends the sign-off and a compliant footer.
- Vary the wording between emails so they don't read like a template.
