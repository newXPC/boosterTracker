#!/usr/bin/env python3
"""
Commons-Scanner: Karten-Stapel nach dem Stream durchzaehlen.

Nutzung: Karte fuer Karte vor die Kamera halten. Jede erkannte Karte wird
mit Preis in booster-tracker-alle.html gelistet, inkl. laufendem Gesamtwert.

Anders als der Stream-Scanner:
  - ALLE Karten werden gelistet (auch Commons)
  - Dieselbe Karte darf MEHRFACH gezaehlt werden (Duplikate im Stapel!)
    -> Zwischen zwei Zaehlungen muss die Karte kurz aus dem Bild
       (oder eine andere Karte gezeigt werden)
"""

import time
from datetime import datetime

import cv2

import stream_monitor_v4
from stream_monitor_v4 import (
    build_reference_features, identify_card, load_price_db,
    update_html_all, FRAME_FEATURES, take_screenshot, NORMAL_INTERVAL,
)

stream_monitor_v4.DEBUG = False  # keine Debug-Zeilen beim Stapel-Scannen


def main():
    print("=" * 60)
    print("COMMONS-SCANNER - Stapel durchzaehlen")
    print("=" * 60)

    price_db = load_price_db()
    print(f"Preisdatenbank: {len(price_db)} Karten")

    print("Berechne Referenz-Features (einmalig)...")
    refs, flann, owner = build_reference_features()
    print(f"Referenz-Features: {len(refs)} Karten")
    print()
    print("Karte zeigen -> wird gezaehlt -> Karte wegnehmen -> naechste.")
    print("Dieselbe Karte 2x im Stapel? Kein Problem, wird wieder gezaehlt,")
    print("sobald sie einmal aus dem Bild war. Stop mit Strg+C.\n")

    orb = cv2.ORB_create(nfeatures=FRAME_FEATURES)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    scanned = []          # alle Scans, neueste zuerst
    total = 0.0
    last_num = None       # zuletzt gezaehlte Karte
    gate_open = True      # erst wieder zaehlen, wenn Karte weg war

    try:
        while True:
            ts = datetime.now().strftime("%H:%M:%S")
            frame = take_screenshot()
            num, inliers = identify_card(frame, refs, orb, flann, owner, bf)

            if num is None:
                # Kein Treffer -> Karte ist weg -> Tor auf fuer naechste Zaehlung
                gate_open = True
            elif num != last_num or gate_open:
                card_data = price_db.get(num)
                if card_data:
                    scanned.insert(0, card_data)
                    price = card_data.get('avg7')
                    if isinstance(price, (int, float)):
                        total += price
                    name = card_data.get('name_de') or card_data.get('name', '?')
                    update_html_all(scanned)
                    total_str = f"{total:.2f}".replace('.', ',')
                    print(f"[{ts}] #{len(scanned)}: {num} {name} "
                          f"(~{price} EUR) | Gesamt: {total_str} EUR")
                    last_num = num
                    gate_open = False

            time.sleep(NORMAL_INTERVAL)

    except KeyboardInterrupt:
        total_str = f"{total:.2f}".replace('.', ',')
        print("\n" + "=" * 60)
        print(f"FERTIG: {len(scanned)} Karten gescannt")
        print(f"GESAMTWERT: {total_str} EUR")
        print("=" * 60)
        print("Komplette Liste: booster-tracker-alle.html")


if __name__ == '__main__':
    main()
