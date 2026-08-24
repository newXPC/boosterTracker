#!/usr/bin/env python3
"""
Booster Tracker v4 - ORB-Feature-Matching + RANSAC-Verifikation.

Robuste Kartenerkennung OHNE Freistellen der Karte:
  1. Screenshot der Camo-Region
  2. ORB-Features im Frame berechnen (markante Bildpunkte)
  3. Gegen vorberechnete Features aller 244 SV10-Karten matchen
  4. Top-Kandidaten geometrisch verifizieren (RANSAC-Homographie)
  5. >= MIN_INLIERS Inlier -> Karte erkannt -> HTML-Update

Funktioniert auch wenn Finger die Karte teilweise verdecken.
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import mss

try:
    import msvcrt  # Windows: Tastatur-Abfrage ohne Blockieren
except ImportError:
    msvcrt = None

BOOSTER_DIR = Path(__file__).parent
PRICE_DB = BOOSTER_DIR / "sv10-preise.json"
CARDS_DIR = BOOSTER_DIR / "sv10_cards_images"
HTML_FILE = BOOSTER_DIR / "booster-tracker.html"
HTML_ALL_FILE = BOOSTER_DIR / "booster-tracker-alle.html"
SCREENSHOT_DIR = BOOSTER_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

NORMAL_INTERVAL = 0.1      # Pause zwischen Scans
FRAME_FEATURES = 3000      # ORB-Features im Frame (hoch, weil Hintergrund/Terminal
                           # viele Features frisst)
MIN_VOTES = 5              # Vorfilter: FLANN-Votes pro Karte
TOP_CANDIDATES = 5         # So viele Kandidaten werden RANSAC-verifiziert
MIN_INLIERS = 15           # RANSAC-Inlier fuer sofortige sichere Erkennung
PERSIST_MIN_INLIERS = 6    # Schwaechere Treffer akzeptieren, wenn...
PERSIST_SCANS = 5          # ...dieselbe Karte so oft in Folge gewinnt
                           # (hilft bei Holo/Full-Art-Karten mit Reflexionen)
MATCH_CONFIRMATIONS = 1    # RANSAC ist sicher genug -> 1 Treffer reicht
RESCAN_COOLDOWN = 3.0      # Sek. nach Erkennung, bevor dieselbe Stelle neu prueft
DEBUG = True               # Pro Scan eine Diagnosezeile ausgeben
MIN_PRICE_FOR_DISPLAY = 1.0  # Karten ohne Hit-Rarity erst ab diesem Preis anzeigen

ENERGY_KEYWORDS = ['energie', 'energy']


def load_price_db():
    with open(PRICE_DB, 'r', encoding='utf-8') as f:
        return {card['number']: card for card in json.load(f)}


def is_energy_card(card_name):
    name = card_name.lower()
    return any(k in name for k in ENERGY_KEYWORDS)


def build_reference_features():
    """ORB-Features fuer alle Referenzkarten berechnen und in einen
    FLANN-LSH-Index packen (ein grosser Suchindex statt 244 Einzelvergleiche).

    Returns: (refs, flann, owner)
      refs:  {num: (keypoints, descriptors)}
      flann: trainierter FLANN-Matcher
      owner: Array, das jeden Index-Deskriptor seiner Karte zuordnet
    """
    orb = cv2.ORB_create(nfeatures=500)
    refs = {}
    all_des = []
    owner = []   # owner[i] = Kartennummer des i-ten Deskriptor-Blocks

    for p in sorted(CARDS_DIR.glob('*.png')):
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        kp, des = orb.detectAndCompute(img, None)
        if des is not None and len(kp) >= 50:
            refs[p.stem] = (kp, des)
            all_des.append(des)
            owner.extend([p.stem] * len(des))

    # FLANN mit LSH-Index (fuer binaere ORB-Deskriptoren)
    index_params = dict(algorithm=6, table_number=8, key_size=16, multi_probe_level=1)
    flann = cv2.FlannBasedMatcher(index_params, dict(checks=32))
    flann.add([np.vstack(all_des)])
    flann.train()

    return refs, flann, np.array(owner)


def take_screenshot():
    """Camo-Fensterbereich als Graustufen-Array holen."""
    with mss.MSS() as sct:
        monitor = sct.monitors[1]
        # Nur die Bildschirmmitte: da zeigt Camo die Karte.
        # Terminal/andere Fenster am Rand werden ignoriert.
        region = {
            'top': int(monitor['height'] * 0.15),
            'left': int(monitor['width'] * 0.32),
            'width': int(monitor['width'] * 0.36),
            'height': int(monitor['height'] * 0.7),
        }
        shot = sct.grab(region)
        img = np.array(shot)
        gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        # CLAHE: verbessert Kontrast bei Reflexionen (Holo-/Full-Art-Karten)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(gray)


def identify_card(frame_gray, refs, orb, flann, owner, bf):
    """Frame per FLANN-Voting + RANSAC gegen alle Referenzkarten matchen.

    Returns: (card_number, inliers) oder (None, 0)
    """
    kp_f, des_f = orb.detectAndCompute(frame_gray, None)
    if des_f is None or len(kp_f) < 50:
        return None, 0, None

    # Stufe 1: FLANN-knnMatch gegen den Gesamtindex, Voting pro Karte
    knn = flann.knnMatch(des_f, k=2)
    votes = {}
    for pair in knn:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.75 * n.distance:  # Lowe ratio test
            num = owner[m.trainIdx]
            votes[num] = votes.get(num, 0) + 1

    candidates = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)
    if DEBUG and candidates:
        top3 = ', '.join(f'{n}:{v}' for n, v in candidates[:3])
        print(f'    [debug] votes: {top3}')
    candidates = [(num, v) for num, v in candidates[:TOP_CANDIDATES] if v >= MIN_VOTES]
    if not candidates:
        return None, 0, None

    # Stufe 2: RANSAC-Verifikation der Top-Kandidaten (praezises BF-Matching)
    best_num, best_inliers = None, 0
    for num, _ in candidates:
        kp_r, des_r = refs[num]
        matches = bf.match(des_f, des_r)
        good = [m for m in matches if m.distance < 50]
        if len(good) < 8:
            continue
        src = np.float32([kp_f[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp_r[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        inliers = int(mask.sum()) if mask is not None else 0
        if inliers > best_inliers:
            best_num, best_inliers = num, inliers

    if DEBUG and best_num:
        status = 'OK' if best_inliers >= MIN_INLIERS else 'schwach'
        print(f'    [debug] RANSAC: {best_num} -> {best_inliers} Inlier ({status})')

    accepted = best_num if best_inliers >= MIN_INLIERS else None
    candidate = best_num if best_inliers >= PERSIST_MIN_INLIERS else None
    return accepted, best_inliers, candidate


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


def render_cards(cards_list, limit=10, highlight_latest=True):
    """Kartenliste als HTML-Bloecke rendern."""
    out = ""
    for i, card in enumerate(cards_list[:limit]):
        latest_class = " latest" if (i == 0 and highlight_latest) else ""
        rarity = card.get('rarity', 'Unknown')
        price = card.get('avg7', 'N/A')
        display_name = card.get('name_de') or card['name']
        out += f"""<div class="card{latest_class}">
  <img class="thumb" src="sv10_cards_images/{card['number']}.png" alt="">
  <div class="info">
    <p class="name">{display_name}</p>
    <p class="set">Ewige Rivalen (DRI) &middot; {card['number']}/182</p>
    <div class="row">
      <span class="chip">{rarity}</span>
      <span class="price">~{price} &euro;</span>
    </div>
  </div>
</div>
"""
    return out


def build_archive_section(display_num, cards_list, counters):
    """Abgeschlossenes Display als zusammenklappbaren Abschnitt rendern."""
    total = sum(c.get('avg7') or 0 for c in cards_list
                if isinstance(c.get('avg7'), (int, float)))
    total_str = f"{total:.2f}".replace('.', ',')
    stats = ' &middot; '.join(f"{v}&times;{k}" for k, v in counters.items() if v > 0) or "keine Hits"
    cards_html = render_cards(cards_list, limit=100, highlight_latest=False)
    return f"""<details class="display-old">
  <summary>
    <span class="d-name">Display {display_num}</span>
    <span class="d-stats">{len(cards_list)} Hits &middot; {stats} &middot; ~{total_str} &euro;</span>
  </summary>
{cards_html}</details>
"""


def update_html(cards_list, counters, display_num=1, archived_html=""):
    if not HTML_FILE.exists():
        return

    cards_html = render_cards(cards_list)
    if not cards_html:
        cards_html = '<p class="empty">Noch keine Hits in diesem Display</p>\n'

    counters_html = f"""<div class="counter c-ex"><div class="num">{counters['ex']}</div><div class="lbl">ex</div></div>
  <div class="counter c-ir"><div class="num">{counters['IR']}</div><div class="lbl">IR</div></div>
  <div class="counter c-fa"><div class="num">{counters['FA']}</div><div class="lbl">FA</div></div>
  <div class="counter c-gold"><div class="num">{counters['Gold']}</div><div class="lbl">Gold</div></div>
  <div class="counter c-sar"><div class="num">{counters['SAR']}</div><div class="lbl">SAR</div></div>"""

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    html = re.sub(
        r'<div class="counters">.*?</div>\n</div>|<div class="counters">.*?</div>',
        f'<div class="counters">\n  {counters_html}\n</div>',
        html, count=1, flags=re.DOTALL
    )
    html = re.sub(
        r'<p class="display-label">.*?(?=<footer>)',
        f'<p class="display-label">Display {display_num} &middot; aktuell</p>\n\n'
        f'{cards_html}\n{archived_html}',
        html, flags=re.DOTALL
    )

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)


def update_html_all(cards_all):
    """Zweite Seite: komplette Liste ALLER gezogenen Karten (inkl. Commons)."""
    if not HTML_ALL_FILE.exists():
        return

    total = 0.0
    rows = ""
    for card in cards_all:  # neueste zuerst
        name = card.get('name_de') or card['name']
        rarity = card.get('rarity', '?')
        price = card.get('avg7')
        hit_class = ' class="hit"' if get_rarity_type(rarity) else ''
        if isinstance(price, (int, float)):
            total += price
            price_str = f"{price:.2f}".replace('.', ',') + " &euro;"
        else:
            price_str = "?"
        rows += (f'<tr{hit_class}><td class="num">{card["number"]}/182</td>'
                 f'<td>{name}</td><td>{rarity}</td>'
                 f'<td class="price">{price_str}</td></tr>\n')

    if not rows:
        rows = '<tr><td colspan="4" class="empty">Noch keine Karten erkannt</td></tr>'

    total_str = f"{total:.2f}".replace('.', ',')

    with open(HTML_ALL_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    html = re.sub(
        r'<div class="stats">.*?(?=<table)',
        f'''<div class="stats">
  <div class="stat"><div class="num">{len(cards_all)}</div><div class="lbl">Karten</div></div>
  <div class="stat"><div class="num">{total_str} &euro;</div><div class="lbl">Gesamtwert</div></div>
</div>

''',
        html, flags=re.DOTALL
    )
    html = re.sub(
        r'<tbody>.*?</tbody>',
        f'<tbody>\n{rows}</tbody>',
        html, flags=re.DOTALL
    )

    with open(HTML_ALL_FILE, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    print("=" * 60)
    print("BOOSTER TRACKER v4 - ORB + RANSAC")
    print("=" * 60)

    price_db = load_price_db()
    print(f"Preisdatenbank: {len(price_db)} Karten")

    print("Berechne Referenz-Features und FLANN-Index (einmalig)...")
    refs, flann, owner = build_reference_features()
    print(f"Referenz-Features: {len(refs)} Karten")
    print("Warte auf Karten...")
    print(">> ENTER druecken = neues Display starten (dieses Fenster muss Fokus haben) <<\n")

    orb = cv2.ORB_create(nfeatures=FRAME_FEATURES)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    cards_list = []
    counters = {'ex': 0, 'IR': 0, 'FA': 0, 'Gold': 0, 'SAR': 0}
    seen_cards = set()

    display_num = 1
    archived_html = ""

    pending_num = None
    pending_count = 0
    last_detect_time = 0
    weak_num = None
    weak_count = 0

    try:
        while True:
            ts = datetime.now().strftime("%H:%M:%S")

            # ENTER im Terminal = aktuelles Display archivieren, neues starten
            if msvcrt and msvcrt.kbhit():
                key = msvcrt.getwch()
                if key == '\r':
                    archived_html = build_archive_section(
                        display_num, cards_list, counters) + archived_html
                    display_num += 1
                    cards_list = []
                    counters = {'ex': 0, 'IR': 0, 'FA': 0, 'Gold': 0, 'SAR': 0}
                    seen_cards = set()
                    pending_num, pending_count = None, 0
                    weak_num, weak_count = None, 0
                    update_html(cards_list, counters, display_num, archived_html)
                    print(f"\n[{ts}] ===== NEUES DISPLAY: Display {display_num} =====\n")

            frame = take_screenshot()

            num, inliers, candidate = identify_card(frame, refs, orb, flann, owner, bf)

            # Beharrlichkeit: schwacher Kandidat gewinnt PERSIST_SCANS mal in
            # Folge (Holo-Reflexionen) -> trotzdem akzeptieren
            if num is None and candidate is not None:
                if candidate == weak_num:
                    weak_count += 1
                else:
                    weak_num, weak_count = candidate, 1
                if weak_count >= PERSIST_SCANS:
                    num = candidate
                    weak_num, weak_count = None, 0  # zuruecksetzen gegen Log-Spam
                    if DEBUG:
                        print(f'    [debug] {candidate} akzeptiert nach '
                              f'{PERSIST_SCANS} konsistenten Scans')
            elif candidate is None:
                weak_num, weak_count = None, 0

            if num:
                if num == pending_num:
                    pending_count += 1
                else:
                    pending_num, pending_count = num, 1

                if pending_count == MATCH_CONFIRMATIONS:
                    if num in seen_cards:
                        # Schon gezaehlt -> nur kurz melden, nicht doppeln
                        if time.time() - last_detect_time > RESCAN_COOLDOWN:
                            print(f"[{ts}] {num} bereits erfasst (skip)")
                            last_detect_time = time.time()
                    else:
                        card_data = price_db.get(num)
                        if card_data:
                            name = card_data.get('name_de') or card_data.get('name', '?')
                            if is_energy_card(name):
                                print(f"[{ts}] Energie -> skip ({name})")
                                seen_cards.add(num)
                            else:
                                seen_cards.add(num)
                                rt = get_rarity_type(card_data.get('rarity', ''))
                                price = card_data.get('avg7') or 0

                                # Nur Hits anzeigen: ex/FA/IR/SAR/Gold oder teuer
                                is_hit = rt is not None or (
                                    isinstance(price, (int, float))
                                    and price >= MIN_PRICE_FOR_DISPLAY
                                )
                                if is_hit:
                                    cards_list.insert(0, card_data)
                                    if rt:
                                        counters[rt] += 1
                                    update_html(cards_list, counters,
                                                display_num, archived_html)
                                    print(f"[{ts}] HIT: {num} {name} "
                                          f"(~{price} EUR, {inliers} Inlier)")
                                else:
                                    print(f"[{ts}] Bulk -> nicht angezeigt: "
                                          f"{num} {name} (~{price} EUR)")
                                last_detect_time = time.time()
            else:
                pending_num, pending_count = None, 0

            time.sleep(NORMAL_INTERVAL)

    except KeyboardInterrupt:
        print(f"\nGestoppt. {len(seen_cards)} Karten erkannt.")
        print(f"SAR: {counters['SAR']}, IR: {counters['IR']}, FA: {counters['FA']}, "
              f"Gold: {counters['Gold']}, ex: {counters['ex']}")


if __name__ == '__main__':
    main()
