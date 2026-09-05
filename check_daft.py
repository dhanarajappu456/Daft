import os
import re
import json
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---- Configuration -------------------------------------------------------
# Paste any Daft.ie search URL(s) here (copy straight from your browser's
# address bar after setting filters on daft.ie). You can add more than one,
# e.g. separate URLs for "apartments" and "studios" or different areas.
SEARCH_URLS = [
    "https://www.daft.ie/property-for-rent/dublin-city/apartments?rentalPrice_to=1500",
    "https://www.daft.ie/property-for-rent/dublin/apartments?rentalPrice_to=1500",
]

STATE_FILE = Path("data/seen_listings.json")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IE,en;q=0.9",
}

LISTING_ID_RE = re.compile(r"/for-rent/[^\"'/]+/(\d+)")
# ---------------------------------------------------------------------------


def load_seen():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(sorted(seen)))


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    if not resp.ok:
        print("Telegram send failed:", resp.status_code, resp.text, file=sys.stderr)


def fetch_listings(url):
    """Return a list of {id, url, title, price} dicts for a Daft search URL."""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = {}
    for a in soup.find_all("a", href=True):
        m = LISTING_ID_RE.search(a["href"])
        if not m:
            continue
        listing_id = m.group(1)
        if listing_id in results:
            continue

        link = a["href"]
        if link.startswith("/"):
            link = "https://www.daft.ie" + link

        card = a.find_parent("li") or a.find_parent("div") or a
        text = " | ".join(t.strip() for t in card.stripped_strings if t.strip())
        price_match = re.search(r"€[\d,]+", text)
        price = price_match.group(0) if price_match else "price n/a"
        title = a.get_text(strip=True) or text[:80]

        results[listing_id] = {"id": listing_id, "url": link, "title": title, "price": price}
    return list(results.values())


def main():
    seen = load_seen()
    new_seen = set(seen)
    new_listings = []

    for search_url in SEARCH_URLS:
        try:
            listings = fetch_listings(search_url)
        except Exception as e:
            print(f"Failed to fetch {search_url}: {e}", file=sys.stderr)
            continue

        if not listings:
            print(f"WARNING: 0 listings parsed from {search_url} "
                  f"(page may be blocked or markup changed).", file=sys.stderr)

        for listing in listings:
            if listing["id"] not in seen:
                new_listings.append(listing)
                new_seen.add(listing["id"])

    if new_listings:
        for listing in new_listings:
            msg = (
                f"\U0001F3E0 <b>New Daft listing</b>\n"
                f"{listing['title']}\n"
                f"{listing['price']}\n"
                f"{listing['url']}"
            )
            send_telegram(msg)
        print(f"Sent {len(new_listings)} new listing(s).")
    else:
        print("No new listings.")

    save_seen(new_seen)


if __name__ == "__main__":
    main()
