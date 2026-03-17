import requests, os, json, re
from bs4 import BeautifulSoup
from datetime import datetime

TRIP_QUERY     = os.environ["TRIP_QUERY"]  # "Grenoble to Les Deux Alpes on March 26"
GITHUB_TOKEN   = os.environ["GH_PAT"]
GITHUB_REPO    = os.environ["GITHUB_REPOSITORY"]

# ── Step 1: search stop codes directly from the site ─────────
def find_stop_code(query):
    """Hit the bus-et-clic autocomplete endpoint to find a stop code."""
    r = requests.get(
        "https://www.bus-et-clic.com/mreso/arrets",
        params={"q": query},
        headers={"User-Agent": "Mozilla/5.0",
                 "X-Requested-With": "XMLHttpRequest"},
        timeout=10
    )
    if r.status_code == 200:
        try:
            results = r.json()
            if results:
                # Return first match — {code: "GRG", name: "Grenoble Gare Routiere"}
                return results[0]
        except:
            pass

    # Fallback: scrape the main page options
    r = requests.get("https://www.bus-et-clic.com/mreso",
                     headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")
    query_lower = query.lower()
    for option in soup.find_all("option"):
        if query_lower in option.get_text().lower():
            return {"code": option["value"], "name": option.get_text().strip()}
    return None

# ── Step 2: parse the natural language query ──────────────────
def parse_query(query):
    """
    Extract from/to/date from a natural language string.
    Handles patterns like:
      'Grenoble to Les Deux Alpes on March 26'
      'Grenoble → Chamrousse le 28 mars'
      'GRG to LDA 2026-03-26'
    """
    query = query.strip()

    # Extract date — try various formats
    date = None
    date_patterns = [
        (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        (r"(\d{2}/\d{2}/\d{4})", "%d/%m/%Y"),
        (r"(\d{1,2}\s+\w+\s+\d{4})", "%d %B %Y"),
    ]
    months_fr = {
        "janvier":"january","février":"february","mars":"march",
        "avril":"april","mai":"may","juin":"june","juillet":"july",
        "août":"august","septembre":"september","octobre":"october",
        "novembre":"november","décembre":"december"
    }

    # Normalize French month names to English
    q_normalized = query.lower()
    for fr, en in months_fr.items():
        q_normalized = q_normalized.replace(fr, en)

    # Try to find a date
    month_names = "january|february|march|april|may|june|july|august|september|october|november|december"
    match = re.search(rf"(\d{{1,2}})\s+({month_names})", q_normalized, re.I)
    if match:
        day   = match.group(1)
        month = match.group(2)
        date  = datetime.strptime(f"{day} {month} 2026", "%d %B %Y").strftime("%Y-%m-%d")

    if not date:
        for pattern, fmt in date_patterns:
            match = re.search(pattern, query)
            if match:
                try:
                    date = datetime.strptime(match.group(1), fmt).strftime("%Y-%m-%d")
                    break
                except:
                    pass

    if not date:
        print("❌ Could not find a date in your query.")
        print("   Try: 'Grenoble to Les Deux Alpes on March 26'")
        exit(1)

    # Remove date from query to help find from/to
    query_clean = re.sub(
        r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{1,2}\s+\w+(\s+\d{4})?|on\s+\w+\s+\d+|le\s+\d+\s+\w+)",
        "", query, flags=re.I
    ).strip()

    # Split on "to", "→", "->", "vers", "pour"
    separators = r"\bto\b|\bvers\b|\bpour\b|→|->"
    parts = re.split(separators, query_clean, maxsplit=1, flags=re.I)

    if len(parts) < 2:
        print("❌ Could not find departure and destination.")
        print("   Try: 'Grenoble to Les Deux Alpes on March 26'")
        exit(1)

    from_query = parts[0].strip()
    to_query   = parts[1].strip()

    return from_query, to_query, date

# ── Step 3: build and verify URL ─────────────────────────────
def build_url(from_code, to_code, date_iso):
    date_encoded = datetime.strptime(date_iso, "%Y-%m-%d").strftime("%d%%2F%m%%2F%Y")

    with open("config.json") as f:
        config = json.load(f)
    token = "52f05913"
    if config["trips"]:
        match = re.search(r"token=([^&]+)", config["trips"][0]["url"])
        if match:
            token = match.group(1)

    return (
        f"https://www.bus-et-clic.com/mreso/resultats"
        f"?token={token}&type=1"
        f"&corresp_start={from_code}&corresp_end={to_code}"
        f"&depart_date={date_encoded}"
        f"&passagers%5BPTF%5D=1&passagers%5BABO%5D=0"
    ), config

def verify_url(url):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    seats_found = any(
        "Place(s) disponible(s)" in li.get_text()
        for li in BeautifulSoup(r.text, "html.parser").find_all("li")
    )
    no_results = "aucune course disponible" in r.text.lower()
    return seats_found, no_results

# ── Main ──────────────────────────────────────────────────────
print(f"🔍 Parsing: '{TRIP_QUERY}'")
from_query, to_query, date = parse_query(TRIP_QUERY)
print(f"   From:  '{from_query}'")
print(f"   To:    '{to_query}'")
print(f"   Date:  {date}")

print(f"\n🔍 Looking up stop codes...")
from_stop = find_stop_code(from_query)
to_stop   = find_stop_code(to_query)

if not from_stop:
    print(f"❌ Could not find stop code for '{from_query}'")
    exit(1)
if not to_stop:
    print(f"❌ Could not find stop code for '{to_query}'")
    exit(1)

print(f"   From: {from_stop['code']} ({from_stop['name']})")
print(f"   To:   {to_stop['code']} ({to_stop['name']})")

url, config = build_url(from_stop["code"], to_stop["code"], date)
print(f"\n🔍 Verifying URL...")
seats_found, no_results = verify_url(url)

if no_results and not seats_found:
    print(f"❌ No trips found for this route and date.")
    print(f"   URL tried: {url}")
    exit(1)

# Save to config
trip_name = f"{from_stop['name']} → {to_stop['name']}"
config["trips"] = [t for t in config["trips"] if t["name"] != trip_name]
config["trips"].append({"name": trip_name, "url": url, "date": date})

with open("config.json", "w") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print(f"\n✅ Added '{trip_name}' to config.json")
print(f"   Seats available: {'yes' if seats_found else 'unknown'}")
