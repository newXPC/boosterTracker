#!/usr/bin/env python3
"""
Baut das komplette Datenpaket fuer ein Set:
  sets/<id>/app_data.json   (Namen DE, Preise, ORB-Features fuer die App)
  sets/<id>/images/*.png    (Referenzbilder)
Und traegt das Set in sets.json ein.

Nutzung:
  python make_set.py sv10          # Ewige Rivalen (nutzt lokale Daten)
  python make_set.py me1           # anderes Set (laedt alles herunter)

Danach: git add + push -> die App laedt das neue Set automatisch.
"""

import base64
import json
import sys
import time
from pathlib import Path

import cv2
import requests

BOOSTER_DIR = Path(__file__).parent
SETS_JSON = BOOSTER_DIR / "sets.json"
N_FEATURES = 400
RETRIES = 8


def api_get(url, params=None):
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(min(2 ** attempt, 15))
    raise RuntimeError(f"API nicht erreichbar: {url}")


def fetch_set_info(set_id):
    data = api_get(f"https://api.pokemontcg.io/v2/sets/{set_id}")["data"]
    return data["name"], data.get("printedTotal") or data.get("total")


def fetch_cards(set_id):
    """Alle Karten des Sets von pokemontcg.io (Preise + Bild-URLs)."""
    cards, page = [], 1
    while True:
        chunk = api_get("https://api.pokemontcg.io/v2/cards",
                        {"q": f"set.id:{set_id}", "page": page, "pageSize": 50})
        if not chunk.get("data"):
            break
        cards.extend(chunk["data"])
        print(f"  Kartenliste Seite {page}: {len(chunk['data'])}")
        page += 1
    return cards


# pokemontcg.io-ID -> tcgdex-ID (tcgdex nutzt zero-padded IDs)
def tcgdex_id(set_id):
    special = {'zsv10pt5': 'sv10.5b', 'rsv10pt5': 'sv10.5w'}
    if set_id in special:
        return special[set_id]
    import re as _re
    m = _re.match(r'^([a-z]+)(\d+)(pt5)?$', set_id)
    if not m:
        return set_id
    prefix, num, pt5 = m.groups()
    padded = num if len(num) > 1 else '0' + num
    return f"{prefix}{padded}" + ('.5' if pt5 else '')


def fetch_german_names(set_id):
    """Returns (kartennamen_dict, deutscher_setname oder None)."""
    try:
        data = api_get(f"https://api.tcgdex.net/v2/de/sets/{tcgdex_id(set_id)}")
        out = {}
        for c in data.get("cards", []):
            try:
                out[str(int(c["localId"]))] = c.get("name", "")
            except (ValueError, KeyError):
                continue
        return out, data.get("name")
    except Exception:
        print("  WARNUNG: keine deutschen Namen gefunden (tcgdex)")
        return {}, None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    set_id = sys.argv[1]

    out_dir = BOOSTER_DIR / "sets" / set_id
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    print(f"Set-Info laden ({set_id})...")
    set_name, printed_total = fetch_set_info(set_id)
    print(f"  {set_name}, {printed_total} Karten im Hauptset")

    de_names, de_set_name = fetch_german_names(set_id)
    if de_set_name:
        set_name = de_set_name  # deutscher Set-Name bevorzugt
    print(f"  Deutsche Namen: {len(de_names)} (Set: {set_name})")

    cards = fetch_cards(set_id)
    print(f"  Karten gesamt: {len(cards)}")

    # Fuer sv10 liegen die Bilder schon lokal
    legacy_imgs = BOOSTER_DIR / "sv10_cards_images" if set_id == "sv10" else None

    orb = cv2.ORB_create(nfeatures=N_FEATURES)
    db = {}
    for i, c in enumerate(cards, 1):
        try:
            num = str(int(c["number"]))
        except ValueError:
            num = str(c["number"])

        img_path = img_dir / f"{num}.png"
        if not img_path.exists():
            if legacy_imgs and (legacy_imgs / f"{num}.png").exists():
                img_path.write_bytes((legacy_imgs / f"{num}.png").read_bytes())
            else:
                url = (c.get("images") or {}).get("small")
                if not url:
                    continue
                for attempt in range(RETRIES):
                    try:
                        r = requests.get(url, timeout=30)
                        if r.status_code == 200:
                            img_path.write_bytes(r.content)
                            break
                    except requests.RequestException:
                        pass
                    time.sleep(min(2 ** attempt, 10))
                else:
                    print(f"  [{num}] Bild nicht ladbar -> skip")
                    continue
                time.sleep(0.2)

        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        kp, des = orb.detectAndCompute(img, None)
        if des is None or len(kp) < 50:
            continue

        prices = (c.get("cardmarket") or {}).get("prices") or {}
        db[num] = {
            "name": de_names.get(num) or c.get("name", "?"),
            "rarity": c.get("rarity", "?"),
            "avg7": prices.get("avg7"),
            "des": base64.b64encode(des.tobytes()).decode("ascii"),
            "n": int(des.shape[0]),
            "kps": [round(v, 1) for k in kp for v in k.pt],
        }
        if i % 50 == 0:
            print(f"  Features: {i}/{len(cards)}")

    with open(out_dir / "app_data.json", "w", encoding="utf-8") as f:
        json.dump(db, f, separators=(",", ":"))
    print(f"  app_data.json: {len(db)} Karten")

    # sets.json aktualisieren
    sets = []
    if SETS_JSON.exists():
        with open(SETS_JSON, encoding="utf-8") as f:
            sets = json.load(f)
    sets = [s for s in sets if s["id"] != set_id]
    sets.append({"id": set_id, "name": set_name, "total": printed_total})
    sets.sort(key=lambda s: s["id"])
    with open(SETS_JSON, "w", encoding="utf-8") as f:
        json.dump(sets, f, indent=2, ensure_ascii=False)

    print(f"FERTIG: sets/{set_id}/ + Eintrag in sets.json")
    print("Jetzt: git add -A && git commit && git push")


if __name__ == "__main__":
    main()
