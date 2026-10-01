import fcntl
import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LEADS_FILE = DATA / "leads.json"        # every business ever seen, keyed by id
QUEUE_FILE = DATA / "queue.json"        # leads waiting for Claude to write an email
DRAFTS_DIR = DATA / "drafts"            # Claude writes <lead_id>.json here
SUPPRESSION_FILE = ROOT / "suppression.txt"


def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_env(name):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing {name} in .env")
    return value


def load_config():
    path = ROOT / "config.yaml"
    if not path.exists():
        raise SystemExit("No config.yaml yet: run `cp config.example.yaml config.yaml` and fill it in.")
    return yaml.safe_load(path.read_text())


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)


def single_instance():
    """Exit if another leads.py / push_drafts.py run is already using the data files."""
    DATA.mkdir(exist_ok=True)
    lock = open(DATA / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another outreach run is in progress; try again when it finishes.")
    return lock  # keep a reference so the lock is held until the process exits


def suppressed():
    """Emails and domains that must never be contacted (one per line)."""
    if not SUPPRESSION_FILE.exists():
        return set()
    return {
        line.strip().lower()
        for line in SUPPRESSION_FILE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def is_suppressed(email, blocked):
    email = email.lower()
    return email in blocked or email.split("@")[-1] in blocked


def add_suppression(email, reason):
    if email.lower() not in suppressed():
        with SUPPRESSION_FILE.open("a") as f:
            f.write(f"# {reason}\n{email.lower()}\n")


def connect_imap():
    import imaplib
    imap = imaplib.IMAP4_SSL(require_env("IMAP_HOST"),
                             int(os.environ.get("IMAP_PORT", "993")))
    imap.login(require_env("EMAIL_ADDRESS"), require_env("EMAIL_PASSWORD"))
    return imap
