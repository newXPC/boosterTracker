#!/usr/bin/env python3
"""
Baut ein JAPANISCHES Set fuer die App — mit SCHAETZWERTEN statt echten Preisen.

Quellen:
  - Namen/Nummern: tcgdex (ja)
  - Kartenbilder + Raritaeten: limitlesstcg.com
  - Preise: Schaetzwert-Tabelle nach Raritaet (jp_estimates.json)
    (fuer JP-Karten gibt es keine verlaessliche freie Preisquelle!)

Nutzung: python make_jp_set.py M2a
"""

import base64
import json
import re
import sys
import time
from pathlib import Path

import cv2
import requests

BOOSTER_DIR = Path(__file__).parent
SETS_JSON = BOOSTER_DIR / "sets.json"
EST_FILE = BOOSTER_DIR / "jp_estimates.json"
N_FEATURES = 400
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# Schaetzwerte in EUR nach Raritaet (bewusst grob, transparent anpassbar)
DEFAULT_ESTIMATES = {
    "Special Art Rare": 25.0,
    "Super Rare": 8.0,
    "Ultra Rare": 30.0,
    "Art Rare": 3.0,
    "Double Rare": 0.6,
    "Rare": 0.2,
    "Uncommon": 0.05,
    "Common": 0.05,
    "_default": 0.1,
}

RARITY_PATTERNS = [
    "Special Art Rare", "Art Rare", "Super Rare", "Ultra Rare",
    "Double Rare", "Uncommon", "Common", "Rare",
]


def get(url, **kw):
    for attempt in range(6):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30, **kw)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(min(2 ** attempt, 10))
    return None


def load_estimates():
    if EST_FILE.exists():
        with open(EST_FILE, encoding='utf-8') as f:
            return json.load(f)
    with open(EST_FILE, 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_ESTIMATES, f, indent=2, ensure_ascii=False)
    return dict(DEFAULT_ESTIMATES)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    set_id = sys.argv[1]
    estimates = load_estimates()

    out_dir = BOOSTER_DIR / "sets" / f"jp-{set_id}"
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    print(f"tcgdex-Daten laden ({set_id})...")
    r = get(f"https://api.tcgdex.net/v2/ja/sets/{set_id}")
    if r is None:
        print("Set nicht gefunden!")
        sys.exit(1)
    data = r.json()
    set_name = data.get("name", set_id)
    official = (data.get("cardCount") or {}).get("official")
    cards = data.get("cards", [])
    print(f"  {set_name}: {len(cards)} Karten (offiziell {official})")

    orb = cv2.ORB_create(nfeatures=N_FEATURES)
    db = {}
    for i, c in enumerate(cards, 1):
        try:
            num = str(int(c["localId"]))
        except (ValueError, KeyError):
            continue
        name = c.get("name", "?")

        # Bild von limitless
        img_path = img_dir / f"{num}.png"
        if not img_path.exists():
            url = (f"https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/"
                   f"tpc/{set_id}/{set_id}_{num}_R_JP_SM.png")
            resp = get(url)
            if resp is None:
                print(f"  [{num}] kein Bild -> skip")
                continue
            img_path.write_bytes(resp.content)
            time.sleep(0.15)

        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        kp, des = orb.detectAndCompute(img, None)
        if des is None or len(kp) < 50:
            continue

        # Raritaet von der limitless-Detailseite
        rarity = None
        detail = get(f"https://limitlesstcg.com/cards/jp/{set_id}/{num}")
        if detail is not None:
            for pat in RARITY_PATTERNS:
                if pat in detail.text:
                    rarity = pat
                    break
        time.sleep(0.15)

        est = estimates.get(rarity, estimates.get("_default", 0.1))
        db[num] = {
            "name": name,
            "rarity": (rarity or "?") + " (JP)",
            "avg7": est,
            "des": base64.b64encode(des.tobytes()).decode("ascii"),
            "n": int(des.shape[0]),
            "kps": [round(v, 1) for k in kp for v in k.pt],
        }
        if i % 40 == 0:
            print(f"  {i}/{len(cards)}...")

    with open(out_dir / "app_data.json", "w", encoding="utf-8") as f:
        json.dump(db, f, separators=(",", ":"), ensure_ascii=False)
    print(f"  app_data.json: {len(db)} Karten")

    sets = []
    if SETS_JSON.exists():
        with open(SETS_JSON, encoding='utf-8') as f:
            sets = json.load(f)
    sets = [s for s in sets if s["id"] != f"jp-{set_id}"]
    sets.append({
        "id": f"jp-{set_id}",
        "name": f"JP · {set_name}",
        "total": official or len(cards),
        "estimate": True,
    })
    sets.sort(key=lambda s: s["id"])
    with open(SETS_JSON, "w", encoding="utf-8") as f:
        json.dump(sets, f, indent=2, ensure_ascii=False)

    print(f"FERTIG: sets/jp-{set_id}/ (Schaetzwerte, estimate=true)")


if __name__ == "__main__":
    main()
