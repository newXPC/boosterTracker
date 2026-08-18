#!/usr/bin/env python3
"""Debug script to test each component"""

import subprocess
import sys
import json
from pathlib import Path

BOOSTER_DIR = Path(__file__).parent
OCR_SCRIPT = BOOSTER_DIR / "cards_ocr.py"
PRICE_DB = BOOSTER_DIR / "sv10-preise.json"
SCREENSHOT_DIR = BOOSTER_DIR / "screenshots"

print("=" * 60)
print("BOOSTER TRACKER DEBUG")
print("=" * 60)

# Check files exist
print("\n1️⃣  Dateien vorhanden?")
print(f"   OCR Script: {'✅' if OCR_SCRIPT.exists() else '❌'} {OCR_SCRIPT}")
print(f"   Preise DB: {'✅' if PRICE_DB.exists() else '❌'} {PRICE_DB}")
print(f"   Screenshot dir: {'✅' if SCREENSHOT_DIR.exists() else '❌'} {SCREENSHOT_DIR}")

# Test OCR on existing screenshots
print("\n2️⃣  Screenshots im Ordner?")
screenshots = list(SCREENSHOT_DIR.glob("live_*.png"))
print(f"   Gefunden: {len(screenshots)} Screenshots")

if screenshots:
    latest = sorted(screenshots)[-1]
    print(f"\n3️⃣  Teste OCR auf letztem Screenshot: {latest.name}")

    try:
        result = subprocess.run(
            [sys.executable, str(OCR_SCRIPT), str(latest), "--json"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            print(f"   ✅ OCR erfolgreich!")
            data = json.loads(result.stdout)
            print(f"   Erkannte Kartennummer: {data.get('card_number', 'KEINE')}")
            print(f"   Kartennummer-Konfidenz: {data.get('confidence', 'N/A')}")

            if data.get('card_number'):
                # Test Lookup
                card_num = data['card_number']
                with open(PRICE_DB, 'r', encoding='utf-8') as f:
                    cards = {c['number']: c for c in json.load(f)}

                if card_num in cards:
                    card = cards[card_num]
                    print(f"\n4️⃣  Kartenlookup erfolgreich!")
                    print(f"   Name: {card.get('name')}")
                    print(f"   Rarität: {card.get('rarity')}")
                    print(f"   Preis: {card.get('avg7')}€")
                else:
                    print(f"\n❌ Karte {card_num} nicht in Datenbank!")
        else:
            print(f"   ❌ OCR fehlgeschlagen!")
            print(f"   Fehler: {result.stderr}")
    except subprocess.TimeoutExpired:
        print(f"   ❌ OCR Timeout (>10 Sek)")
    except json.JSONDecodeError:
        print(f"   ❌ OCR Output kein JSON")
        print(f"   Raw output: {result.stdout}")
else:
    print("   ⚠️  Keine Screenshots gefunden - Script hat nichts gemacht?")

print("\n5️⃣  HTML-Datei?")
html_file = BOOSTER_DIR / "booster-tracker.html"
print(f"   {'✅' if html_file.exists() else '❌'} {html_file}")

print("\n" + "=" * 60)
print("EMPFEHLUNGEN:")
print("=" * 60)
if not screenshots:
    print("❌ Script macht keine Screenshots!")
    print("   → Versuche manuell: python stream_monitor.py -v")
elif screenshots and len(list(SCREENSHOT_DIR.glob("live_*.png"))) < 3:
    print("⚠️  Nur wenige Screenshots")
    print("   → Script läuft aber langsam?")
else:
    print("✅ Screenshots werden gemacht")
    print("❓ Aber OCR funktioniert nicht")
    print("   → Prüfe ob cards_ocr.py richtig konfiguriert ist")
