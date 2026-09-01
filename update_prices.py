#!/usr/bin/env python3
"""
Aktualisiert die Cardmarket-Preise in sv10-preise.json ueber api.pokemontcg.io.

Vor jedem Stream (oder 1x pro Woche) ausfuehren:
    python update_prices.py

Namen (auch deutsche) und Raritaeten bleiben unangetastet — nur die
Preisfelder (trend, low, avg7, avg30, revHoloTrend, updated) werden erneuert.
"""

import json
import time
from datetime import date
from pathlib import Path

import requests

PRICE_DB = Path(__file__).parent / "sv10-preise.json"
SET_ID = "sv10"
PAGE_SIZE = 50    # kleinere Seiten = zuverlaessiger bei der flatterigen API
RETRIES = 8


def fetch_page(page):
    for attempt in range(RETRIES):
        try:
            r = requests.get(
                "https://api.pokemontcg.io/v2/cards",
                params={"q": f"set.id:{SET_ID}", "page": page,
                        "pageSize": PAGE_SIZE,
                        "select": "number,cardmarket"},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json().get("data", [])
        except requests.RequestException:
            pass
        wait = min(2 ** attempt, 15)
        print(f"  Seite {page}: Fehler, neuer Versuch in {wait}s...")
        time.sleep(wait)
    print(f"  Seite {page}: AUFGEGEBEN — diese Karten behalten alte Preise")
    return None  # Teilausfall: Rest trotzdem verarbeiten


def main():
    with open(PRICE_DB, encoding="utf-8") as f:
        cards = json.load(f)
    by_number = {str(c["number"]): c for c in cards}
    print(f"Lokale Tabelle: {len(cards)} Karten")

    api_cards = []
    total_pages = (244 + PAGE_SIZE - 1) // PAGE_SIZE
    for page in range(1, total_pages + 1):
        chunk = fetch_page(page)
        if chunk is None:
            continue  # Teilausfall
        if not chunk:
            break
        api_cards.extend(chunk)
        print(f"  Seite {page}: {len(chunk)} Karten geladen")
    print(f"API gesamt: {len(api_cards)} Karten")

    today = date.today().isoformat()
    updated = 0
    for ac in api_cards:
        num = str(int(ac["number"])) if str(ac["number"]).isdigit() else str(ac["number"])
        card = by_number.get(num)
        prices = (ac.get("cardmarket") or {}).get("prices") or {}
        if card is None or not prices:
            continue
        card["trend"] = prices.get("trendPrice")
        card["low"] = prices.get("lowPrice")
        card["avg7"] = prices.get("avg7")
        card["avg30"] = prices.get("avg30")
        card["revHoloTrend"] = prices.get("reverseHoloTrend")
        card["updated"] = today
        updated += 1

    with open(PRICE_DB, "w", encoding="utf-8") as f:
        json.dump(cards, f, indent=2, ensure_ascii=False)

    print(f"\nFertig: {updated}/{len(cards)} Karten aktualisiert (Stand {today})")
    if updated < len(cards):
        print(f"Hinweis: {len(cards) - updated} Karten ohne neue Preisdaten "
              f"(behalten den alten Stand)")


if __name__ == "__main__":
    main()
