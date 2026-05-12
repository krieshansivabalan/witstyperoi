"""
LinkedIn Scraper — runs locally using Playwright in a real Chromium browser.
Pulls your LinkedIn connections and recent message conversations, then loads
them directly into the leads database.

Usage:
    python linkedin_scraper.py

You will be prompted for your LinkedIn email and password. Credentials are
used only in the live browser session and are never stored anywhere.
"""

import getpass
import json
import re
import sqlite3
import sys
import time
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

import database as db

# ─── Config ───────────────────────────────────────────────────────────────────

LINKEDIN_BASE = "https://www.linkedin.com"
CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
MESSAGING_URL = "https://www.linkedin.com/messaging/"
MAX_CONNECTIONS = 1000
MAX_CONVERSATIONS = 200

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    db.init_db()
    print("\n━━━━ LinkedIn Lead Scraper ━━━━")
    print("Opens a real browser window — do not close it while running.\n")

    email = input("LinkedIn email: ").strip()
    password = getpass.getpass("LinkedIn password: ")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()

        try:
            _login(page, email, password)
            print("\n✓ Logged in")

            print("\n→ Scraping connections...")
            connections = _scrape_connections(page)
            print(f"  Found {len(connections)} connections")

            print("\n→ Scraping recent messages...")
            messages = _scrape_messages(page)
            print(f"  Found message threads for {len(messages)} people")

            # Merge message data into connections
            msg_by_url = {m["linkedin_url"]: m for m in messages}
            for c in connections:
                if c["linkedin_url"] in msg_by_url:
                    c.update({k: v for k, v in msg_by_url[c["linkedin_url"]].items() if v})

            # Also add any messaged people not in connections list
            conn_urls = {c["linkedin_url"] for c in connections}
            for m in messages:
                if m["linkedin_url"] not in conn_urls:
                    connections.append(m)

            print(f"\n→ Importing {len(connections)} leads into database...")
            imported, skipped = _import_leads(connections)
            print(f"  ✓ Imported: {imported}  Skipped (duplicates): {skipped}")

        except KeyboardInterrupt:
            print("\nInterrupted by user.")
        except Exception as e:
            print(f"\nError: {e}")
            import traceback; traceback.print_exc()
        finally:
            ctx.close()
            browser.close()

    print("\n✓ Done. Open http://localhost:5000 to view your leads.\n")


# ─── Login ────────────────────────────────────────────────────────────────────

def _login(page, email, password):
    page.goto(f"{LINKEDIN_BASE}/login", wait_until="domcontentloaded")
    page.fill("#username", email)
    page.fill("#password", password)
    page.click('[type="submit"]')

    # Wait for redirect — may require 2FA
    try:
        page.wait_for_url("**/feed/**", timeout=30000)
    except PlaywrightTimeout:
        # Might be on 2FA or checkpoint page
        print("\n  LinkedIn requires verification. Complete it in the browser window.")
        print("  Press Enter here once you're logged in and can see the feed...")
        input()


# ─── Connections ──────────────────────────────────────────────────────────────

def _scrape_connections(page):
    page.goto(CONNECTIONS_URL, wait_until="domcontentloaded")
    _wait(page, 2)

    connections = []
    seen_urls = set()
    last_count = -1

    while len(connections) < MAX_CONNECTIONS:
        cards = page.query_selector_all("li.mn-connection-card")
        for card in cards:
            try:
                link_el = card.query_selector("a.mn-connection-card__link")
                if not link_el:
                    continue
                href = link_el.get_attribute("href") or ""
                profile_url = _clean_li_url(href)
                if profile_url in seen_urls:
                    continue
                seen_urls.add(profile_url)

                name_el = card.query_selector(".mn-connection-card__name")
                name = name_el.inner_text().strip() if name_el else ""

                occ_el = card.query_selector(".mn-connection-card__occupation")
                occupation = occ_el.inner_text().strip() if occ_el else ""

                connected_el = card.query_selector(".mn-connection-card__connected-at time")
                connected_raw = connected_el.get_attribute("datetime") if connected_el else ""

                if name:
                    connections.append({
                        "name": name,
                        "company": _extract_company(occupation),
                        "occupation": occupation,
                        "linkedin_url": profile_url,
                        "linkedin_profile_id": profile_url,
                        "connected_at": connected_raw or datetime.utcnow().isoformat(),
                        "email": "",
                        "phone": "",
                        "notes": occupation,
                    })
            except Exception:
                pass

        # Scroll to load more
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        _wait(page, 1.5)

        if len(connections) == last_count:
            break  # No new items loaded
        last_count = len(connections)

    return connections


# ─── Messages ─────────────────────────────────────────────────────────────────

def _scrape_messages(page):
    page.goto(MESSAGING_URL, wait_until="domcontentloaded")
    _wait(page, 2)

    people = []
    seen = set()
    threads_processed = 0

    thread_items = page.query_selector_all(".msg-conversation-listitem")

    for item in thread_items[:MAX_CONVERSATIONS]:
        try:
            name_el = item.query_selector(".msg-conversation-listitem__participant-names span")
            name = name_el.inner_text().strip() if name_el else ""
            if not name or name in seen:
                continue

            # Click the conversation to get profile link
            item.click()
            _wait(page, 1)

            profile_url = ""
            header_link = page.query_selector(".msg-thread__link-to-profile")
            if header_link:
                href = header_link.get_attribute("href") or ""
                profile_url = _clean_li_url(href)

            if not profile_url:
                continue

            seen.add(name)
            threads_processed += 1

            people.append({
                "name": name,
                "linkedin_url": profile_url,
                "linkedin_profile_id": profile_url,
                "company": "",
                "email": "",
                "phone": "",
                "connected_at": datetime.utcnow().isoformat(),
                "notes": "",
            })

            if threads_processed >= MAX_CONVERSATIONS:
                break

        except Exception:
            pass

    return people


# ─── Import ───────────────────────────────────────────────────────────────────

def _import_leads(leads):
    imported = 0
    skipped = 0
    for lead in leads:
        if not lead.get("name"):
            skipped += 1
            continue
        try:
            db.create_lead(lead)
            imported += 1
        except Exception:
            skipped += 1
    return imported, skipped


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean_li_url(href):
    if not href:
        return ""
    href = href.split("?")[0].rstrip("/")
    if href.startswith("/"):
        return f"https://www.linkedin.com{href}"
    return href


def _extract_company(occupation):
    """Try to extract company from 'Title at Company' or just return occupation."""
    if " at " in occupation:
        return occupation.split(" at ", 1)[1].strip()
    if " @ " in occupation:
        return occupation.split(" @ ", 1)[1].strip()
    return ""


def _wait(page, seconds):
    page.wait_for_timeout(int(seconds * 1000))


if __name__ == "__main__":
    main()
