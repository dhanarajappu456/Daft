import os
import re
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import requests

# ---- Configuration -------------------------------------------------------
SEARCH_URLS = [
    "https://www.daft.ie/property-for-rent/dublin-city/apartments?rentalPrice_to=1500",
    "https://www.daft.ie/property-for-rent/dublin/apartments?rentalPrice_to=1500",
]

STATE_FILE = Path("data/seen_listings.json")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

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


def parse_listings(html):
    soup = BeautifulSoup(html, "html.parser")
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


def fetch_listings(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    # give Cloudflare's JS challenge (if shown) a few seconds to resolve
    page.wait_for_timeout(6000)

    title = (page.title() or "").lower()
    if "just a moment" in title or "attention required" in title or "checking your browser" in title:
        raise RuntimeError(f"Blocked by Cloudflare challenge page (title={title!r})")

    html = page.content()
    listings = parse_listings(html)
    if not listings:
        # Save a snippet to logs so we can diagnose markup/blocking issues
        print("DEBUG page title:", page.title(), file=sys.stderr)
        print("DEBUG html length:", len(html), file=sys.stderr)
    return listings


def main():
    seen = load_seen()
    new_seen = set(seen)
    new_listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="en-IE",
            timezone_id="Europe/Dublin",
            viewport={"width": 1280, "height": 900},
        )
        # Basic stealth: hide the automation flag most bot-detection checks for
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )
        page = context.new_page()

        for search_url in SEARCH_URLS:
            try:
                listings = fetch_listings(page, search_url)
            except Exception as e:
                print(f"Failed to fetch {search_url}: {e}", file=sys.stderr)
                continue

            for listing in listings:
                if listing["id"] not in seen:
                    new_listings.append(listing)
                    new_seen.add(listing["id"])

        browser.close()

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
