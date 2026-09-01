#!/usr/bin/env python3
"""
Exportiert ORB-Deskriptoren + Kartendaten fuer die Handy-Web-App (app.html).

Erzeugt app_data.json mit pro Karte:
  - name_de, rarity, avg7
  - ORB-Deskriptoren (base64, 400 Features)
  - Keypoint-Positionen (fuer RANSAC-Verifikation)
"""

import base64
import json
from pathlib import Path

import cv2

BOOSTER_DIR = Path(__file__).parent
CARDS_DIR = BOOSTER_DIR / "sv10_cards_images"
PRICE_DB = BOOSTER_DIR / "sv10-preise.json"
OUT = BOOSTER_DIR / "app_data.json"

N_FEATURES = 400


def main():
    with open(PRICE_DB, encoding="utf-8") as f:
        prices = {str(c["number"]): c for c in json.load(f)}

    orb = cv2.ORB_create(nfeatures=N_FEATURES)
    out = {}
    for p in sorted(CARDS_DIR.glob("*.png")):
        num = p.stem
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        kp, des = orb.detectAndCompute(img, None)
        if des is None or len(kp) < 50:
            continue
        info = prices.get(num, {})
        out[num] = {
            "name": info.get("name_de") or info.get("name") or "?",
            "rarity": info.get("rarity", "?"),
            "avg7": info.get("avg7"),
            "des": base64.b64encode(des.tobytes()).decode("ascii"),
            "n": int(des.shape[0]),
            "kps": [round(v, 1) for k in kp for v in k.pt],
        }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))

    size_mb = OUT.stat().st_size / 1e6
    print(f"OK: {len(out)} Karten -> {OUT.name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
