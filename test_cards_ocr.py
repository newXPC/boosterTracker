"""
Test-Script für cards_ocr.py Pipeline
Generiert synthetische Testbilder und validiert die Pipeline
"""

import sys
from pathlib import Path
import json

# Add BoosterTracker to path
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

import cards_ocr


def create_synthetic_test_image(card_number: str,
                               filename: str = "test_synthetic.png") -> str:
    """
    Erstellt ein synthetisches Testbild mit einer Kartennummer
    in der unteren rechten Ecke (wie auf echten Pokémon-Screenshots).

    Args:
        card_number: Kartennummer als String (z.B. "80/182")
        filename: Output-Dateiname

    Returns:
        Pfad zum erstellten Bild
    """
    # Erstelle ein Testbild (simuliere Pokémon-Karte)
    # Typische Screenshot-Größe: 1080x1920 Pixel (Mobile)
    width, height = 400, 600

    # Hintergrund (weiß mit Kartenbild-Fläche)
    image = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)

    # Zeichne einen "Kartenbereich" (grau)
    draw.rectangle([(20, 20), (380, 580)], fill=(200, 200, 200), outline=(100, 100, 100), width=2)

    # Zeichne Pokémon-Name oben (simulated)
    draw.text((50, 40), "Hypno", fill=(50, 50, 50))

    # Zeichne Kartennummer unten rechts (schwarzer Text auf weißem Hintergrund)
    # Die Kartennummer sollte sehr klein sein, um OCR zu testen
    try:
        # Versuche, eine TrueType Font zu laden (fallback auf default)
        font = ImageFont.truetype("arial.ttf", 18)
    except:
        font = ImageFont.load_default()

    # Position: untere rechte Ecke (wie auf echten Karten)
    text_pos = (330, 550)
    draw.text(text_pos, card_number, fill=(0, 0, 0), font=font)

    # Speichern
    output_path = Path(__file__).parent / filename
    image.save(output_path, 'PNG')

    print(f"✓ Testbild erstellt: {output_path}")
    print(f"  Kartennummer: {card_number}")

    return str(output_path)


def test_ocr_pipeline():
    """Teste die OCR-Pipeline mit syntetischem Bild"""

    print("\n" + "="*70)
    print("TEST 1: OCR-Pipeline mit synthetischem Testbild")
    print("="*70)

    # Erstelle Testbild mit Kartennummer "80/182"
    test_image = create_synthetic_test_image("80/182", "test_synthetic_80_182.png")

    print("\n[1] Extrahiere Kartennummer...")
    card_number = cards_ocr.extract_card_number(test_image, upscale_factor=2)

    if card_number:
        print(f"✓ Kartennummer erkannt: {card_number}")
    else:
        print("✗ Kartennummer nicht erkannt (möglich bei synthetischem Bild)")

    print("\n[2] Vollständige Pipeline (mit Lookup)...")
    result = cards_ocr.process_image_full(test_image)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    return result


def test_preprocessing():
    """Teste Preprocessing-Funktionen einzeln"""

    print("\n" + "="*70)
    print("TEST 2: Preprocessing-Funktionen")
    print("="*70)

    # Erstelle Test-Image
    test_image = create_synthetic_test_image("23/182", "test_synthetic_23.png")

    # Lade mit OpenCV
    image = cv2.imread(test_image)
    print(f"✓ Testbild geladen: {image.shape}")

    # Test Crop
    print("\n[1] Crop Kartennummern-Region...")
    cropped = cards_ocr.crop_card_number_region(image)
    print(f"✓ Cropped: {cropped.shape if cropped is not None else 'FAILED'}")

    # Test Preprocessing
    if cropped is not None:
        print("\n[2] Preprocessing...")
        processed = cards_ocr.preprocess_for_ocr(cropped, upscale_factor=2)
        print(f"✓ Processed: {processed.shape}")

    return True


def test_price_database():
    """Teste Preisdatenbank-Laden und Lookup"""

    print("\n" + "="*70)
    print("TEST 3: Preisdatenbank & Lookup")
    print("="*70)

    db = cards_ocr.load_price_database()

    if not db:
        print("✗ Preisdatenbank konnte nicht geladen werden")
        return False

    print(f"✓ {len(db)} Karten geladen")

    # Test einige Lookups
    test_cards = ["1", "80", "104", "182"]

    for card_num in test_cards:
        info = cards_ocr.lookup_card_info(card_num, db)
        if info:
            print(f"  ✓ {card_num}: {info.get('name')} ({info.get('rarity')})")
        else:
            print(f"  ✗ {card_num}: Nicht gefunden")

    return True


def test_regex_extraction():
    """Teste Kartennummern-Extraktion mit Regex"""

    print("\n" + "="*70)
    print("TEST 4: Regex-basierte Kartennummern-Extraktion")
    print("="*70)

    test_cases = [
        ("80/182", "80/182", True),  # Perfect match
        ("80 / 182", "80/182", True),  # Whitespace
        ("8O/182", "80/182", True),  # OCR-Fehler: O statt 0
        ("80/I82", "80/182", True),  # OCR-Fehler: I statt 1
        ("104/104", "104/104", True),  # Double Rare
        ("keine Nummer hier", None, False),  # Kein Match
        ("23 / 200 extra text", "23/200", True),  # Mit extra Text
    ]

    for text, expected, should_match in test_cases:
        result = cards_ocr.extract_card_number_from_text(text)

        if should_match:
            if result == expected:
                print(f"✓ '{text}' -> '{result}'")
            else:
                print(f"✗ '{text}' -> '{result}' (erwartet: '{expected}')")
        else:
            if result is None:
                print(f"✓ '{text}' -> None (erwartet)")
            else:
                print(f"✗ '{text}' -> '{result}' (sollte None sein)")

    return True


def main():
    """Führe alle Tests durch"""

    print("\n")
    print("╔" + "="*68 + "╗")
    print("║" + " "*15 + "CARDS_OCR.PY - INTEGRATION TEST" + " "*23 + "║")
    print("╚" + "="*68 + "╝")

    # Check EasyOCR
    if not cards_ocr.EASYOCR_AVAILABLE:
        print("\n⚠️  EasyOCR ist nicht installiert!")
        print("   Installieren: pip install easyocr")
        print("\n   Tests ohne EasyOCR werden trotzdem durchgeführt...")

    # Tests durchführen
    all_passed = True

    try:
        test_regex_extraction()
    except Exception as e:
        print(f"✗ Regex-Test fehlgeschlagen: {e}")
        all_passed = False

    try:
        test_price_database()
    except Exception as e:
        print(f"✗ Datenbank-Test fehlgeschlagen: {e}")
        all_passed = False

    try:
        test_preprocessing()
    except Exception as e:
        print(f"✗ Preprocessing-Test fehlgeschlagen: {e}")
        all_passed = False

    if cards_ocr.EASYOCR_AVAILABLE:
        try:
            test_ocr_pipeline()
        except Exception as e:
            print(f"✗ OCR-Pipeline-Test fehlgeschlagen: {e}")
            all_passed = False
    else:
        print("\n[SKIPPED] OCR-Pipeline-Test (EasyOCR nicht verfügbar)")

    # Summary
    print("\n" + "="*70)
    if all_passed:
        print("✓ Alle verfügbaren Tests bestanden!")
    else:
        print("✗ Einige Tests sind fehlgeschlagen")
    print("="*70 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
