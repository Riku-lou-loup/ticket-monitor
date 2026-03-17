import requests, os, re, json, smtplib
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from datetime import date

GMAIL_USER      = os.environ["GMAIL_USER"]
GMAIL_PASS      = os.environ["GMAIL_APP_PASS"]
GMAIL_RECIPIENT = os.environ["GMAIL_RECIPIENT"]
GITHUB_TOKEN    = os.environ["GH_PAT"]
GITHUB_REPO     = os.environ["GITHUB_REPOSITORY"]

def get_seats(url):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    for li in soup.find_all("li"):
        text = li.get_text()
        if "Place(s) disponible(s)" in text:
            match = re.search(r"\d+", text)
            if match:
                return int(match.group())
    return None

def get_stored(key):
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables/{key}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                 "Accept": "application/vnd.github+json"}
    )
    return r.json().get("value") if r.status_code == 200 else None

def store(key, value):
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}",
               "Accept": "application/vnd.github+json"}
    data = {"name": key, "value": str(value)}
    r = requests.patch(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables/{key}",
        headers=headers, json=data
    )
    if r.status_code == 404:
        requests.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables",
            headers=headers, json=data
        )

def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = GMAIL_RECIPIENT
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_PASS)
        smtp.send_message(msg)

def safe_key(name):
    """Convert trip name to a valid variable key e.g. SEATS_GRENOBLE_PRAPOUTEL"""
    return "SEATS_" + re.sub(r"[^A-Z0-9]", "_", name.upper())

# ── Main ──────────────────────────────────────────────────────
with open("config.json") as f:
    config = json.load(f)

today = date.today()

for trip in config["trips"]:
    name      = trip["name"]
    url       = trip["url"]
    trip_date = date.fromisoformat(trip["date"])

    # Skip trips whose date has passed
    if trip_date < today:
        print(f"[{name}] Date passed — skipping.")
        continue

    key      = safe_key(name)
    current  = get_seats(url)
    previous = get_stored(key)
    previous = int(previous) if previous is not None else None

    print(f"[{name}] Current: {current} | Previous: {previous}")

    if current is None:
        print(f"[{name}] No seats found.")
        if previous and previous > 0:
            send_email(
                f"🚌 {name} — Plus de places !",
                f"Plus aucune place disponible.\n\nRéserver : {url}"
            )
            store(key, 0)

    elif previous is None or current != previous:
        diff = current - (previous or 0)
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        send_email(
            f"🚌 {name} — {current} places ({diff_str})",
            f"Changement détecté !\n\n"
            f"Avant : {previous} place(s)\n"
            f"Maintenant : {current} place(s)\n\n"
            f"Réserver maintenant :\n{url}"
        )
        print(f"[{name}] Change detected — email sent.")
        store(key, current)

    else:
        print(f"[{name}] No change ({current} seats).")