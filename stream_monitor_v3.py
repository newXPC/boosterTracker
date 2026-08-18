#!/usr/bin/env python3
"""
Booster Tracker v3 - Image-Hashing statt OCR.

Erkennt Karten anhand des GANZEN Kartenbilds (perceptual hashing),
nicht anhand der winzigen Kartennummer. Technik nach
https://github.com/NolanAmblard/Pokemon-Card-Scanner:
  1. Screenshot der Camo-Region
  2. Kartenkontur finden (Canny + groesste 4-Eck-Kontur)
  3. Perspektivisch auf Standardformat entzerren
  4. 4 Hashes berechnen (average, whash, phash, dhash)
  5. Gegen sv10_hashes.json vergleichen -> beste Uebereinstimmung
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import imagehash
import mss
from PIL import Image

BOOSTER_DIR = Path(__file__).parent
PRICE_DB = BOOSTER_DIR / "sv10-preise.json"
HASHES_DB = BOOSTER_DIR / "sv10_hashes.json"
HTML_FILE = BOOSTER_DIR / "booster-tracker.html"
SCREENSHOT_DIR = BOOSTER_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

# Kartenformat (6.6cm x 8.8cm skaliert)
CARD_W, CARD_H = 330, 440

NORMAL_INTERVAL = 1.0     # Hashing ist billig -> jede Sekunde pruefen
FAST_INTERVAL = 0.3
FAST_MODE_DURATION = 20

# Hash-Distanz: kleiner = aehnlicher. Cutoff nach Experimenten anpassen.
HASH_CUTOFF = 18          # Summe ueber die besten Einzeldistanzen
MATCH_CONFIRMATIONS = 2   # Karte muss in N Frames hintereinander gleich erkannt werden

ENERGY_KEYWORDS = ['energie', 'energy']


def load_price_db():
    with open(PRICE_DB, 'r', encoding='utf-8') as f:
        return {card['number']: card for card in json.load(f)}


def load_hashes_db():
    """Laedt sv10_hashes.json und parst die Hashes zurueck in imagehash-Objekte."""
    if not HASHES_DB.exists():
        print(f"FEHLER: {HASHES_DB} fehlt. Erst generate_sv10_hashes.py ausfuehren!")
        sys.exit(1)

    with open(HASHES_DB, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    db = {}
    for num, entry in raw.items():
        h = entry['hashes']
        db[num] = {
            'name': entry['name'],
            'average': imagehash.hex_to_hash(h['average']),
            'whash': imagehash.hex_to_hash(h['whash']),
            'phash': imagehash.hex_to_hash(h['phash']),
            'dhash': imagehash.hex_to_hash(h['dhash']),
        }
    return db


def is_energy_card(card_name):
    name = card_name.lower()
    return any(k in name for k in ENERGY_KEYWORDS)


def take_screenshot():
    """Camo-Fensterbereich als BGR-numpy-Array holen."""
    with mss.MSS() as sct:
        monitor = sct.monitors[1]
        region = {
            'top': int(monitor['height'] * 0.1),
            'left': int(monitor['width'] * 0.2),
            'width': int(monitor['width'] * 0.6),
            'height': int(monitor['height'] * 0.8),
        }
        shot = sct.grab(region)
        img = np.array(shot)  # BGRA
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def find_card_in_frame(frame):
    """Findet die groesste 4-Eck-Kontur (die Karte) und entzerrt sie.

    Returns: entzerrtes Kartenbild (CARD_W x CARD_H) oder None.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edged = cv2.Canny(blurred, 100, 200)

    kernel = np.ones((5, 5))
    dilated = cv2.dilate(edged, kernel, iterations=2)
    eroded = cv2.erode(dilated, kernel, iterations=1)

    contours, _ = cv2.findContours(eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_corners, max_area = None, 0
    min_area = frame.shape[0] * frame.shape[1] * 0.05  # Karte muss min. 5% des Bilds sein

    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area <= max_area:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            best_corners, max_area = approx, area

    if best_corners is None:
        return None

    # Ecken sortieren: topLeft, topRight, bottomLeft, bottomRight
    pts = best_corners.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).flatten()
    ordered = np.float32([
        pts[np.argmin(s)],   # topLeft: kleinste Summe
        pts[np.argmin(d)],   # topRight: kleinste Differenz (x-y)
        pts[np.argmax(d)],   # bottomLeft: groesste Differenz
        pts[np.argmax(s)],   # bottomRight: groesste Summe
    ])

    dst = np.float32([[0, 0], [CARD_W, 0], [0, CARD_H], [CARD_W, CARD_H]])
    matrix = cv2.getPerspectiveTransform(ordered, dst)
    return cv2.warpPerspective(frame, matrix, (CARD_W, CARD_H))


def match_card(card_img, hashes_db):
    """Berechnet Hashes des entzerrten Kartenbilds und sucht die beste Uebereinstimmung.

    Returns: (card_number, distance) oder (None, None)
    """
    rgb = cv2.cvtColor(card_img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)

    h_avg = imagehash.average_hash(pil_img)
    h_w = imagehash.whash(pil_img)
    h_p = imagehash.phash(pil_img)
    h_d = imagehash.dhash(pil_img)

    best_num, best_dist = None, float('inf')
    for num, entry in hashes_db.items():
        # Summe der 4 Hash-Distanzen als Gesamtmass
        dist = (
            (h_avg - entry['average'])
            + (h_w - entry['whash'])
            + (h_p - entry['phash'])
            + (h_d - entry['dhash'])
        )
        if dist < best_dist:
            best_num, best_dist = num, dist

    if best_dist <= HASH_CUTOFF * 4:  # Cutoff auf 4 Hashes verteilt
        return best_num, best_dist
    return None, best_dist


def get_rarity_type(rarity_str):
    r = str(rarity_str).lower()
    if 'special' in r and 'illustration' in r:
        return 'SAR'
    if 'illustration' in r:
        return 'IR'
    if 'full art' in r or 'ultra' in r:
        return 'FA'
    if 'gold' in r or 'hyper' in r or 'secret' in r:
        return 'Gold'
    if 'double rare' in r or r.strip() == 'ex':
        return 'ex'
    return None


def update_html(cards_list, counters):
    if not HTML_FILE.exists():
        return

    cards_html = ""
    for i, card in enumerate(cards_list[:10]):
        latest_class = " latest" if i == 0 else ""
        rarity = card.get('rarity', 'Unknown')
        price = card.get('avg7', 'N/A')
        cards_html += f"""<div class="card{latest_class}">
  <p class="name">{card['name']}</p>
  <p class="set">Ewige Rivalen (DRI) &middot; {card['number']}</p>
  <div class="row">
    <span class="chip">{rarity}</span>
    <span class="price">~{price} &euro;</span>
  </div>
</div>
"""

    counters_html = f"""<div class="counter c-sar"><div class="num">{counters['SAR']}</div><div class="lbl">SAR</div></div>
  <div class="counter c-ir"><div class="num">{counters['IR']}</div><div class="lbl">IR</div></div>
  <div class="counter c-fa"><div class="num">{counters['FA']}</div><div class="lbl">FA</div></div>
  <div class="counter c-gold"><div class="num">{counters['Gold']}</div><div class="lbl">Gold</div></div>
  <div class="counter c-ex"><div class="num">{counters['ex']}</div><div class="lbl">ex</div></div>"""

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    html = re.sub(
        r'<div class="counters">.*?</div>\n</div>|<div class="counters">.*?</div>',
        f'<div class="counters">\n  {counters_html}\n</div>',
        html, count=1, flags=re.DOTALL
    )
    html = re.sub(
        r'<p class="display-label">.*?(?=<footer>)',
        f'<p class="display-label">Display 1 &middot; aktuell</p>\n\n{cards_html}\n',
        html, flags=re.DOTALL
    )

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    print("=" * 60)
    print("BOOSTER TRACKER v3 - IMAGE HASHING")
    print("=" * 60)

    price_db = load_price_db()
    hashes_db = load_hashes_db()
    print(f"Preisdatenbank: {len(price_db)} Karten")
    print(f"Hash-Datenbank: {len(hashes_db)} Karten")
    print("Warte auf Karten...\n")

    cards_list = []
    counters = {'SAR': 0, 'IR': 0, 'FA': 0, 'Gold': 0, 'ex': 0}
    seen_cards = set()

    interval = NORMAL_INTERVAL
    last_card_time = 0
    pending_num = None
    pending_count = 0
    frame_no = 0

    try:
        while True:
            frame_no += 1
            ts = datetime.now().strftime("%H:%M:%S")

            frame = take_screenshot()
            card_img = find_card_in_frame(frame)

            if card_img is not None:
                num, dist = match_card(card_img, hashes_db)

                if num:
                    # Debug-Bild der letzten Erkennung speichern
                    cv2.imwrite(str(SCREENSHOT_DIR / "last_match.png"), card_img)

                    # Bestaetigung ueber mehrere Frames (gegen Fehlerkennungen)
                    if num == pending_num:
                        pending_count += 1
                    else:
                        pending_num, pending_count = num, 1

                    if pending_count >= MATCH_CONFIRMATIONS and num not in seen_cards:
                        card_data = price_db.get(num)
                        if card_data:
                            name = card_data.get('name', '?')
                            if is_energy_card(name):
                                print(f"[{ts}] Energie -> skip ({name})")
                            else:
                                seen_cards.add(num)
                                cards_list.insert(0, card_data)
                                rt = get_rarity_type(card_data.get('rarity', ''))
                                if rt:
                                    counters[rt] += 1
                                update_html(cards_list, counters)
                                price = card_data.get('avg7', 'N/A')
                                print(f"[{ts}] KARTE: {num} {name} (~{price} EUR, dist={dist})")
                                last_card_time = time.time()
                                interval = FAST_INTERVAL
            else:
                pending_num, pending_count = None, 0

            if interval == FAST_INTERVAL and time.time() - last_card_time > FAST_MODE_DURATION:
                interval = NORMAL_INTERVAL
                print(f"[{ts}] Zurueck auf normales Tempo")

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\nGestoppt. {len(seen_cards)} Karten erkannt.")
        print(f"SAR: {counters['SAR']}, IR: {counters['IR']}, FA: {counters['FA']}, "
              f"Gold: {counters['Gold']}, ex: {counters['ex']}")


if __name__ == '__main__':
    main()
