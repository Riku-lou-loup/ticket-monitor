import requests, os, re, json
from bs4 import BeautifulSoup
from datetime import datetime

TRIP_QUERY   = os.environ["TRIP_QUERY"]
GITHUB_TOKEN = os.environ["GH_PAT"]
GITHUB_REPO  = os.environ["GITHUB_REPOSITORY"]

STOPS = {
    "grenoble":        {"code": "GRG", "operator": "mreso"},
    "grenoble gare":   {"code": "GRG", "operator": "mreso"},
    "gare routiere":   {"code": "GRG", "operator": "mreso"},
    "prapoutel":       {"code": "PPO", "operator": "mreso"},
    "patte d'oie":     {"code": "PPO", "operator": "mreso"},
    "chamrousse":      {"code": "CHA", "operator": "mreso"},
    "7 laux":          {"code": "SLX", "operator": "mreso"},
    "sept laux":       {"code": "SLX", "operator": "mreso"},
    "villard de lans": {"code": "VDL", "operator": "mreso"},
    "villard":         {"code": "VDL", "operator": "mreso"},
    "autrans":         {"code": "AUT", "operator": "mreso"},
    "lans en vercors": {"code": "LEV", "operator": "mreso"},
    "deux alpes":      {"code": "DAT", "operator": "transaltitude"},
    "les deux alpes":  {"code": "DAT", "operator": "transaltitude"},
    "2 alpes":         {"code": "DAT", "operator": "transaltitude"},
    "alpe d'huez":     {"code": "ADH", "operator": "transaltitude"},
    "alpe huez":       {"code": "ADH", "operator": "transaltitude"},
    "bourg d'oisans":  {"code": "BDO", "operator": "transaltitude"},
    "bourg oisans":    {"code": "BDO", "operator": "transaltitude"},
    "venosc":          {"code": "VEN", "operator": "transaltitude"},
}

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

def find_stop_code(query):
    q = query.lower().strip()
    if q in STOPS:
        return STOPS[q]
    for key, val in STOPS.items():
        if key in q or q in key:
            return val
    return None

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
    return match.group(1) if match else None

def parse_query(query):
    query = query.strip()
    months_fr = {
        "janvier":"january","février":"february","mars":"march",
        "avril":"april","mai":"may","juin":"june","juillet":"july",
        "août":"august","septembre":"september","octobre":"october",
        "novembre":"november","décembre":"december"
    }
    q_normalized = query.lower()
    for fr, en in months_fr.items():
        q_normalized = q_normalized.replace(fr, en)

    date = None

    match = re.search(r"(\d{4}-\d{2}-\d{2})", q_normalized)
    if match:
        date = match.group(1)

    if not date:
        month_names = "january|february|march|april|may|june|july|august|september|october|november|december"
        match = re.search(rf"(?:on\s+)?({month_names})\s+(\d{{1,2}})", q_normalized, re.I)
        if match:
            date = datetime.strptime(f"{match.group(2)} {match.group(1)} 2026", "%d %B %Y").strftime("%Y-%m-%d")

    if not date:
        month_names = "january|february|march|april|may|june|july|august|september|october|november|december"
        match = re.search(rf"(?:le\s+)?(\d{{1,2}})\s+({month_names})", q_normalized, re.I)
        if match:
            date = datetime.strptime(f"{match.group(1)} {match.group(2)} 2026", "%d %B %Y").strftime("%Y-%m-%d")

    if not date:
        print("❌ Could not find a date in your query.")
        print("   Try: 'Grenoble to Prapoutel on March 21'")
        exit(1)

    date_pattern = (
        r"(?:on\s+)?"
        r"(?:\d{4}-\d{2}-\d{2}"
        r"|\d{2}/\d{2}/\d{4}"
        r"|(?:january|february|march|april|may|june|july|august"
        r"|september|october|november|december)\s+\d{1,2}"
        r"|\d{1,2}\s+(?:january|february|march|april|may|june|july|august"
        r"|september|october|november|december)"
        r"|le\s+\d{1,2}\s+\w+)"
    )
    query_clean = re.sub(date_pattern, "", q_normalized, flags=re.I).strip()

    parts = re.split(r"\bto\b|\bvers\b|\bpour\b|→|->", query_clean, maxsplit=1, flags=re.I)
    if len(parts) < 2:
        print("❌ Could not find departure and destination.")
        print("   Try: 'Grenoble to Prapoutel on March 21'")
        exit(1)

    return parts[0].strip(), parts[1].strip(), date

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
print(f"   From: '{from_query}'")
print(f"   To:   '{to_query}'")
print(f"   Date: {date}")

print(f"\n🔍 Looking up stop codes...")
from_stop = find_stop_code(from_query)
to_stop   = find_stop_code(to_query)

if not from_stop:
    print(f"❌ Could not find stop code for '{from_query}'")
    print(f"   Known stops: {', '.join(STOPS.keys())}")
    exit(1)
if not to_stop:
    print(f"❌ Could not find stop code for '{to_query}'")
    print(f"   Known stops: {', '.join(STOPS.keys())}")
    exit(1)

print(f"   From: {from_stop['code']} (operator: {from_stop['operator']})")
print(f"   To:   {to_stop['code']}   (operator: {to_stop['operator']})")

operator = to_stop["operator"] if from_stop["operator"] != to_stop["operator"] else from_stop["operator"]
op       = OPERATORS[operator]

print(f"\n🔍 Fetching live token for {operator}...")
token = fetch_token(operator)
if not token:
    print(f"❌ Could not fetch token for {operator}")
    exit(1)
print(f"   Token: {token}")

date_encoded = datetime.strptime(date, "%Y-%m-%d").strftime("%d%%2F%m%%2F%Y")
url = (
    f"{op['base']}?token={token}&type={op['type']}"
    f"&corresp_start={from_stop['code']}&corresp_end={to_stop['code']}"
    f"&depart_date={date_encoded}"
    f"&depart_time=&retour_date={date_encoded}&retour_time="
    f"&passagers%5BPTF%5D=1{op['extra']}"
)

print(f"\n🔍 Verifying URL...")
seats_found, no_results = verify_url(url)

if no_results and not seats_found:
    print(f"❌ No trips found for this route and date.")
    print(f"   URL tried: {url}")
    exit(1)

with open("config.json") as f:
    config = json.load(f)

trip_name = f"{from_query.title()} → {to_query.title()}"
config["trips"] = [t for t in config["trips"] if t["name"] != trip_name]
config["trips"].append({
    "name":          trip_name,
    "corresp_start": from_stop["code"],
    "corresp_end":   to_stop["code"],
    "operator":      operator,
    "date":          date
})

with open("config.json", "w") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print(f"\n✅ Added '{trip_name}' to config.json ({operator})")
print(f"   Seats available: {'yes' if seats_found else 'unknown'}")
print(f"   URL: {url}")