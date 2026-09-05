import os
import re
import sys
import imaplib
import email
from email.header import decode_header

import requests

# ---- Configuration -------------------------------------------------------
IMAP_HOST = os.environ.get("IMAP_HOST") or "imap.gmail.com"
IMAP_USER = os.environ["IMAP_USER"]
IMAP_PASSWORD = os.environ["IMAP_PASSWORD"]

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Loose default - tighten this once you've seen a real Daft alert land in
# your inbox and checked its actual "From" address.
SENDER_FILTER = os.environ.get("DAFT_SENDER_FILTER") or "daft.ie"

LISTING_URL_RE = re.compile(r"https://www\.daft\.ie/for-rent/[^\s\"'<>]+")
# ---------------------------------------------------------------------------


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


def decode_str(value):
    if not value:
        return ""
    parts = decode_header(value)
    out = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            out += text.decode(enc or "utf-8", errors="ignore")
        else:
            out += text
    return out


def get_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html" and "attachment" not in str(part.get("Content-Disposition") or ""):
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="ignore")


def main():
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    conn.login(IMAP_USER, IMAP_PASSWORD)
    conn.select("INBOX")

    status, data = conn.search(None, f'(UNSEEN FROM "{SENDER_FILTER}")')
    if status != "OK":
        print("IMAP search failed:", status, data, file=sys.stderr)
        conn.logout()
        return

    ids = data[0].split()
    if not ids:
        print("No new Daft alert emails.")
        conn.logout()
        return

    print(f"Found {len(ids)} new Daft alert email(s).")

    for msg_id in ids:
        status, msg_data = conn.fetch(msg_id, "(RFC822)")
        if status != "OK":
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        subject = decode_str(msg.get("Subject"))
        sender = decode_str(msg.get("From"))
        body = get_body(msg)

        links = sorted(set(LISTING_URL_RE.findall(body)))

        if links:
            for link in links:
                send_telegram(f"\U0001F3E0 <b>New Daft alert</b>\n{subject}\n{link}")
        else:
            send_telegram(
                f"\U0001F3E0 <b>New Daft alert</b>\n{subject}\n"
                f"(from {sender} - couldn't extract a listing link, check your inbox)"
            )

        # Mark as read so it isn't processed again next run
        conn.store(msg_id, "+FLAGS", "\\Seen")

    conn.logout()


if __name__ == "__main__":
    main()
