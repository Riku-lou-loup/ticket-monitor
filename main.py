import requests, os, re
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
import smtplib

URL = (
    "https://www.bus-et-clic.com/mreso/resultats"
    "?token=52f05913&type=1&ligne_id=15"
    "&corresp_start=GRG&corresp_end=PPO"
    "&depart_date=19%2F03%2F2026"
    "&passagers%5BPTF%5D=1&passagers%5BABO%5D=0"
)

GITHUB_TOKEN = os.environ["GH_PAT"]
GITHUB_REPO  = os.environ["GITHUB_REPOSITORY"]  # auto-set by Actions
GMAIL_USER   = os.environ["GMAIL_USER"]
GMAIL_PASS   = os.environ["GMAIL_APP_PASS"]
GMAIL_RECIPIENT = os.environ["GMAIL_RECIPIENT"]
def get_seats():
    r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    for li in soup.find_all("li"):
        text = li.get_text()
        if "Place(s) disponible(s)" in text:
            match = re.search(r"\d+", text)
            if match:
                return int(match.group())
    return None

def get_stored_seats():
    """Read previous seat count from a GitHub Actions variable."""
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables/LAST_SEATS",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                 "Accept": "application/vnd.github+json"}
    )
    if r.status_code == 200:
        return int(r.json()["value"])
    return None  # variable doesn't exist yet

def store_seats(count):
    """Write current seat count to a GitHub Actions variable."""
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}",
               "Accept": "application/vnd.github+json"}
    data = {"name": "LAST_SEATS", "value": str(count)}
    # Try update first, then create if it doesn't exist
    r = requests.patch(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/variables/LAST_SEATS",
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

# ── Main ──────────────────────────────────────────────────────
current = get_seats()
previous = get_stored_seats()

print(f"Current: {current} seats | Previous: {previous} seats")

if current is None:
    print("No trip found or sold out.")
    if previous is not None and previous > 0:
        send_email(
            "🚌 M réso — Plus de places disponibles !",
            f"Le trajet GRENOBLE → PRAPOUTEL n'a plus de places.\n\n{URL}"
        )
    store_seats(0)

elif previous is None or current != previous:
    # Something changed — notify
    if previous is None:
        msg = f"Première vérification : {current} place(s) disponible(s)."
    elif current < previous:
        msg = f"Les places diminuent : {previous} → {current} place(s) disponible(s) !"
    else:
        msg = f"Les places augmentent : {previous} → {current} place(s) disponible(s)."

    send_email(
        f"🚌 M réso — {current} places ({'+' if current > (previous or 0) else ''}{current - (previous or 0)})",
        f"{msg}\n\nRéserver maintenant :\n{URL}"
    )
    print(f"Change detected — email sent: {msg}")
    store_seats(current)

else:
    print(f"No change ({current} seats). No email sent.")