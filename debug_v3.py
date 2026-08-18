#!/usr/bin/env python3
"""Debug fuer stream_monitor_v3: zeigt jeden Pipeline-Schritt.

Nutzung: Karte vor die Kamera halten, dann ausfuehren.
Speichert Zwischenschritte nach debug_v3_output/ und zeigt Top-3-Matches.
"""

import sys
from pathlib import Path

import cv2
import imagehash
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from stream_monitor_v3 import (
    take_screenshot, find_card_in_frame, load_hashes_db, HASH_CUTOFF
)

OUT = Path(__file__).parent / "debug_v3_output"
OUT.mkdir(exist_ok=True)

print("Mache Screenshot... (Karte jetzt vor die Kamera halten!)")
frame = take_screenshot()
cv2.imwrite(str(OUT / "01_frame.png"), frame)
print(f"1. Screenshot: {frame.shape} -> 01_frame.png")

# Kantenerkennung sichtbar machen
gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
blurred = cv2.GaussianBlur(gray, (3, 3), 0)
edged = cv2.Canny(blurred, 100, 200)
cv2.imwrite(str(OUT / "02_edges.png"), edged)
print("2. Kanten -> 02_edges.png")

card_img = find_card_in_frame(frame)
if card_img is None:
    print()
    print("!! KEINE KARTENKONTUR GEFUNDEN !!")
    print("   -> Schau dir 02_edges.png an: Ist der Kartenrand als")
    print("      geschlossenes Rechteck sichtbar?")
    print("   Haeufige Ursachen: Karte zu klein im Bild, Rand verdeckt")
    print("   durch Finger, zu wenig Kontrast zum Hintergrund.")
    sys.exit(0)

cv2.imwrite(str(OUT / "03_warped_card.png"), card_img)
print("3. Entzerrte Karte -> 03_warped_card.png")

# Matchen mit Details
hashes_db = load_hashes_db()
rgb = cv2.cvtColor(card_img, cv2.COLOR_BGR2RGB)
pil_img = Image.fromarray(rgb)
ha = imagehash.average_hash(pil_img)
hw = imagehash.whash(pil_img)
hp = imagehash.phash(pil_img)
hd = imagehash.dhash(pil_img)

scored = []
for num, e in hashes_db.items():
    dist = (ha - e['average']) + (hw - e['whash']) + (hp - e['phash']) + (hd - e['dhash'])
    scored.append((dist, num, e['name']))
scored.sort()

print()
print(f"Top-3 Matches (Cutoff: {HASH_CUTOFF * 4}):")
for dist, num, name in scored[:3]:
    marker = "  <-- MATCH" if dist <= HASH_CUTOFF * 4 else ""
    print(f"  {num}: {name} (dist={dist}){marker}")
