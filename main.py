import requests, os, re, json, smtplib
from bs4 import BeautifulSoup
from email.mime.text import MIMEText
from datetime import date, datetime

GMAIL_USER      = os.environ["GMAIL_USER"]
GMAIL_PASS      = os.environ["GMAIL_APP_PASS"]
GMAIL_RECIPIENT = os.environ["GMAIL_RECIPIENT"]
GITHUB_TOKEN    = os.environ["GH_PAT"]
GITHUB_REPO     = os.environ["GITHUB_REPOSITORY"]

OPERATORS = {
    "mreso": {
        "type":  "1",
        "base":  "https://www.bus-et-clic.com/mreso/resultats",
        "extra": "",
    },
    "transaltitude": {
        "type":  "2",
        "base":  "https://www.bus-et-clic.com/transaltitude/resultats",
        "extra": "&transaltitude_flags=1",
    },
}

# ── Token ─────────────────────────────────────────────────────
def fetch_token(operator):
    urls = {
        "mreso":         "https://www.bus-et-clic.com/mreso",
        "transaltitude": "https://www.bus-et-clic.com/transaltitude",
    }
    r = requests.get(urls[operator], headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    token_input = soup.find("input", {"name": "token"})
    if token_input:
        return token_input.get("value")
    match = re.search(r"token=([a-f0-9]+)", r.text)
    if match:
        return match.group(1)
    return None

# ── Scrapers ──────────────────────────────────────────────────
def get_seats_busetchic(trip):
    token = fetch_token(trip["operator"])
    if not token:
        print(f"  ❌ Could not fetch token for {trip['operator']}")
        return None
    op = OPERATORS[trip["operator"]]
    date_encoded = datetime.strptime(trip["date"], "%Y-%m-%d").strftime("%d%%2F%m%%2F%Y")
    url = (
        f"{op['base']}?token={token}&type={op['type']}"
        f"&corresp_start={trip['corresp_start']}&corresp_end={trip['corresp_end']}"
        f"&depart_date={date_encoded}"
        f"&depart_time=&retour_date={date_encoded}&retour_time="
        f"&passagers%5BPTF%5D=1{op['extra']}"
    )
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    for li in soup.find_all("li"):
        text = li.get_text()
        if "Place(s) disponible(s)" in text:
            match = re.search(r"\d+", text)
            if match:
                return int(match.group())
    return None

def get_seats_billetweb(trip):
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    url         = trip["url"]
    target_date = trip["date"]
    pickup      = trip.get("pickup")

    dt = datetime.strptime(target_date, "%Y-%m-%d")
    # Linux strftime supports %-d (no leading zero)
    date_str = dt.strftime("%a %b %-d, %Y")  # "Sat Mar 21, 2026"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.goto(url, wait_until="load", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeout:
            pass  # networkidle may never fire; continue and try the selector anyway
        try:
            page.wait_for_selector(".shop_step1_session_date", timeout=30000)
        except PlaywrightTimeout:
            print(f"  ⚠️  Selector not found — page snippet:\n{page.content()[:2000]}")
            browser.close()
            return None
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "html.parser")

    for date_span in soup.find_all("span", class_="shop_step1_session_date"):
        if date_str in date_span.get_text():
            parent = date_span.find_parent("div", class_="shop_step1_name")
            if not parent:
                continue

            if pickup is None:
                # Return total for the date
                avail = parent.find("span", class_="shop_step1_session_availability")
                if avail:
                    match = re.search(r"\d+", avail.get_text())
                    return int(match.group()) if match else 0
            else:
                # Return count for specific pickup point
                for container in parent.find_all("span", class_="shop_step1_name_container"):
                    name_span = container.find("span", class_="shop_step1_name_text")
                    if name_span and pickup.lower() in name_span.get_text().lower():
                        avail = container.find("div", class_="shop_step1_availability")
                        if avail:
                            text = avail.get_text().strip()
                            if re.search(r"complet|sold.?out|épuisé", text, re.I):
                                return 0
                            match = re.search(r"\d+", text)
                            return int(match.group()) if match else 0
    return None

def get_seats_for_trip(trip):
    scraper = trip.get("scraper", "busetchic")
    if scraper == "billetweb":
        return get_seats_billetweb(trip)
    else:
        return get_seats_busetchic(trip)

# ── GitHub variables (persist state between runs) ─────────────
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

# ── Email ─────────────────────────────────────────────────────
def send_email(subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = GMAIL_RECIPIENT
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_PASS)
        smtp.send_message(msg)

def safe_key(name):
    return "SEATS_" + re.sub(r"[^A-Z0-9]", "_", name.upper())

# ── Main ──────────────────────────────────────────────────────
with open("config.json") as f:
    config = json.load(f)

today = date.today()

for trip in config["trips"]:
    name      = trip["name"]
    trip_date = date.fromisoformat(trip["date"])

    if trip_date < today:
        print(f"[{name}] Date passed — skipping.")
        continue

    key      = safe_key(name)
    current  = get_seats_for_trip(trip)
    previous = get_stored(key)
    previous = int(previous) if previous is not None else None

    print(f"[{name}] Current: {current} | Previous: {previous}")

    if current is None:
        print(f"[{name}] No seats found or scrape failed.")
        if previous and previous > 0:
            send_email(
                f"🚌 {name} — Plus de places !",
                f"Plus aucune place disponible.\n\nRéserver : {trip.get('url', '')}"
            )
            store(key, 0)

    elif previous is None or current != previous:
        diff     = current - (previous or 0)
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        book_url = trip.get("url", "")
        send_email(
            f"🚌 {name} — {current} places ({diff_str})",
            f"Changement détecté !\n\n"
            f"Avant     : {previous} place(s)\n"
            f"Maintenant: {current} place(s)\n\n"
            f"Réserver maintenant :\n{book_url}"
        )
        print(f"[{name}] Change detected — email sent.")
        store(key, current)

    else:
        print(f"[{name}] No change ({current} seats).")