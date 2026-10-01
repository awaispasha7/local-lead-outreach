"""Find local-business leads via SerpAPI, find a contact email on their website, and queue them.

Usage: python3 leads.py
Output: data/queue.json (new leads with an email, ready for Claude to write to).
"""
import re
import sys
from datetime import date
from urllib.parse import urljoin, urlparse

import requests

from common import (
    single_instance,
    DATA, LEADS_FILE, QUEUE_FILE, is_suppressed, load_config, load_env,
    read_json, require_env, suppressed, write_json,
)

SERPAPI_URL = "https://serpapi.com/search.json"
CITIES_FILE = DATA / "cities.json"  # cache of city -> data_cid
RUNS_FILE = DATA / "runs.json"      # {today: number of runs}
CATEGORIES_FILE = DATA / "lsa_categories.json"
CATEGORIES_URL = "https://serpapi.com/google-local-services-queries.json"
CONTACT_PATHS = ["", "/contact", "/contact-us", "/about", "/about-us"]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JUNK_EMAIL = re.compile(
    r"\.(png|jpe?g|gif|webp|svg)$|example\.|sentry|wixpress|domain\.com|yourname|email\.com|godaddy",
    re.I,
)
PREFERRED_PREFIXES = ("info", "contact", "office", "hello", "service", "sales", "admin")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def serp(params):
    """Run a SerpAPI search. Errors are reported without the URL so the API key never gets printed."""
    params = {**params, "api_key": require_env("SERPAPI_KEY")}
    try:
        resp = requests.get(SERPAPI_URL, params=params, timeout=60)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"  SerpAPI request failed: {type(exc).__name__}")
        return {}
    if "error" in data and not any(k in data for k in ("local_ads", "local_results", "place_results")):
        print(f"  SerpAPI: {data['error']}")
    return data


def lsa_category(niche):
    """Map a niche to a Local Services category key ("Plumber", "plumber" or "Plumbing" all work)."""
    if not CATEGORIES_FILE.exists():
        write_json(CATEGORIES_FILE, requests.get(CATEGORIES_URL, timeout=30).json())
    categories = read_json(CATEGORIES_FILE, {})
    wanted = niche.strip().lower().replace(" ", "_")
    for key, label in categories.items():
        if wanted in (key, label.lower().replace(" ", "_")):
            return key
    return None


def first_place(data):
    if data.get("place_results"):
        return data["place_results"]
    results = data.get("local_results") or []
    return results[0] if results else {}


def city_cid(city, cache):
    if city not in cache:
        cache[city] = first_place(serp({"engine": "google_maps", "type": "search", "q": city})).get("data_cid")
        write_json(CITIES_FILE, cache)
    return cache[city]


def local_services_leads(niche, city, cache):
    category = lsa_category(niche)
    if not category:
        print(f"  '{niche}' is not a Local Services category; skipping. Valid names: {CATEGORIES_URL}")
        return
    cid = city_cid(city, cache)
    if not cid:
        print(f"  Could not resolve a Google CID for {city}; skipping")
        return
    for ad in serp({"engine": "google_local_services", "q": category, "data_cid": cid}).get("local_ads", []):
        yield {
            "id": f"lsa-{ad.get('pid') or ad.get('cid') or ad.get('bid')}",
            "name": ad.get("title"),
            "phone": ad.get("phone"),
            "rating": ad.get("rating"),
            "reviews": ad.get("reviews"),
            "type": ad.get("type"),
            "years_in_business": ad.get("years_in_business"),
            "service_area": ad.get("service_area"),
            "hours": ad.get("hours"),
            "google_badge": ad.get("badge"),
            "website": None,  # looked up lazily, only for new leads
        }


def maps_leads(niche, city):
    data = serp({"engine": "google_maps", "type": "search", "q": f"{niche} in {city}"})
    for r in data.get("local_results", []):
        yield {
            "id": f"maps-{r.get('data_cid') or r.get('place_id')}",
            "name": r.get("title"),
            "phone": r.get("phone"),
            "rating": r.get("rating"),
            "reviews": r.get("reviews"),
            "type": r.get("type"),
            "address": r.get("address"),
            "hours": r.get("operating_hours"),
            "website": r.get("website"),
        }


def lookup_website(name, city):
    return first_place(serp({"engine": "google_maps", "type": "search", "q": f"{name} {city}"})).get("website")


def decode_cfemail(hex_str):
    key = int(hex_str[:2], 16)
    return "".join(chr(int(hex_str[i:i + 2], 16) ^ key) for i in range(2, len(hex_str), 2))


def find_email(website):
    """Scan the homepage and common contact pages; prefer addresses on the business's own domain."""
    site_domain = (urlparse(website).hostname or "").removeprefix("www.")
    found = []
    for path in CONTACT_PATHS:
        try:
            resp = requests.get(urljoin(website, path), headers=HEADERS, timeout=15)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue
        html = resp.text
        candidates = EMAIL_RE.findall(html)
        candidates += [decode_cfemail(h) for h in re.findall(r'data-cfemail="([0-9a-fA-F]+)"', html)]
        for email in candidates:
            email = email.strip(".").lower()
            if not JUNK_EMAIL.search(email) and email not in found:
                found.append(email)
        if any(e.endswith("@" + site_domain) for e in found):
            break

    def rank(email):
        local, _, domain = email.partition("@")
        return (domain != site_domain and not domain.endswith("." + site_domain),
                not local.startswith(PREFERRED_PREFIXES))

    return sorted(found, key=rank)[0] if found else None


def claim_run(config):
    """Enforce runs_per_day; `--force` bypasses it for a manual run."""
    runs = read_json(RUNS_FILE, {})
    today = date.today().isoformat()
    allowed = config.get("runs_per_day", 1)
    if runs.get(today, 0) >= allowed and "--force" not in sys.argv:
        raise SystemExit(f"Already ran {runs[today]}/{allowed} times today (runs_per_day). Use --force to override.")
    write_json(RUNS_FILE, {today: runs.get(today, 0) + 1})


def main():
    load_env()
    _lock = single_instance()
    config = load_config()
    claim_run(config)
    leads = read_json(LEADS_FILE, {})
    queue = read_json(QUEUE_FILE, [])
    # Recover leads marked queued whose queue entry was lost (e.g. an interrupted run).
    in_queue = {lead["id"] for lead in queue}
    queue += [lead for lead in leads.values() if lead["status"] == "queued" and lead["id"] not in in_queue]
    cache = read_json(CITIES_FILE, {})
    blocked = suppressed()
    queued_emails = {lead["email"] for lead in leads.values() if lead.get("email")}
    # The same business can appear under several niches with different ids.
    seen_names = {(lead["name"].lower(), lead["city"]) for lead in leads.values() if lead.get("name")}
    limit = config.get("max_new_leads_per_run", 20)
    added = 0

    for city in config["cities"]:
        for niche in filter(None, config["niches"]):
            if added >= limit:
                break
            print(f"Searching {niche} in {city}...")
            if config.get("source") == "maps":
                results = maps_leads(niche, city)
            else:
                results = local_services_leads(niche, city, cache)
            for lead in results:
                if added >= limit:
                    break
                name_key = ((lead["name"] or "").lower(), city)
                if lead["id"] in leads or name_key in seen_names:
                    continue
                seen_names.add(name_key)
                lead.update(niche=niche, city=city, found_on=date.today().isoformat())
                if not lead["website"]:
                    lead["website"] = lookup_website(lead["name"], city)
                lead["email"] = find_email(lead["website"]) if lead["website"] else None

                if not lead["email"]:
                    lead["status"] = "no_email"
                elif is_suppressed(lead["email"], blocked) or lead["email"] in queued_emails:
                    lead["status"] = "skipped"
                else:
                    lead["status"] = "queued"
                    queue.append(lead)
                    queued_emails.add(lead["email"])
                    added += 1
                leads[lead["id"]] = lead
                print(f"  {lead['name']}: {lead['status']} {lead['email'] or ''}")
                write_json(LEADS_FILE, leads)
                write_json(QUEUE_FILE, queue)

    write_json(QUEUE_FILE, queue)
    print(f"\n{added} new leads queued. {len(queue)} waiting in data/queue.json.")


if __name__ == "__main__":
    main()
