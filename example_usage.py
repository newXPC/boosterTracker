"""
Beispiele für die Nutzung der cards_ocr.py Pipeline
"""

import json
from pathlib import Path
from cards_ocr import (
    extract_card_number,
    process_image_full,
    load_price_database,
    lookup_card_info
)


def example_1_simple_ocr():
    """
    Beispiel 1: Nur OCR - Kartennummer extrahieren
    """
    print("\n" + "="*70)
    print("BEISPIEL 1: Einfache OCR - Kartennummer extrahieren")
    print("="*70)

    image_path = "live_1.png"  # Ersetze mit echtem Screenshot

    card_number = extract_card_number(image_path, upscale_factor=2, gpu=False)

    if card_number:
        print(f"✓ Kartennummer: {card_number}")
    else:
        print("✗ Kartennummer nicht erkannt")


def example_2_full_pipeline():
    """
    Beispiel 2: Vollständige Pipeline - OCR + Datenbankenlookup
    """
    print("\n" + "="*70)
    print("BEISPIEL 2: Vollständige Pipeline - OCR + Lookup")
    print("="*70)

    image_path = "live_1.png"

    result = process_image_full(image_path)

    if result["success"]:
        print(f"""
Kartennummer:  {result['number']}
Name:          {result['name']}
Seltenheit:    {result['rarity']}
Preis (Trend): €{result['price']:.2f}
""")
    else:
        print(f"Fehler: {result['error']}")

    # Als JSON speichern
    output_file = f"result_{Path(image_path).stem}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Ergebnis gespeichert: {output_file}")


def example_3_batch_processing():
    """
    Beispiel 3: Batch-Processing - Mehrere Bilder verarbeiten
    """
    print("\n" + "="*70)
    print("BEISPIEL 3: Batch-Processing - Mehrere Screenshots")
    print("="*70)

    image_dir = Path.cwd()
    image_files = sorted(image_dir.glob("live_*.png"))

    if not image_files:
        print("Keine live_*.png Dateien gefunden")
        return

    results = []

    for i, image_path in enumerate(image_files, 1):
        print(f"[{i}/{len(image_files)}] Verarbeite {image_path.name}...", end=" ")

        result = process_image_full(str(image_path))

        if result["success"]:
            print(f"✓ {result['number']}")
            results.append(result)
        else:
            print(f"✗ {result['error']}")

    # Speichere Batch-Ergebnisse
    with open("batch_results.json", 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✓ {len(results)}/{len(image_files)} Karten erkannt")
    print(f"Ergebnisse gespeichert: batch_results.json")


def example_4_custom_preprocessing():
    """
    Beispiel 4: Custom Upscaling-Faktor
    """
    print("\n" + "="*70)
    print("BEISPIEL 4: Custom Preprocessing - Verschiedene Upscaling-Faktoren")
    print("="*70)

    image_path = "live_1.png"

    for upscale_factor in [1, 2, 3]:
        print(f"Upscale-Faktor: {upscale_factor}x", end=" -> ")

        card_number = extract_card_number(
            image_path,
            upscale_factor=upscale_factor,
            gpu=False
        )

        if card_number:
            print(f"✓ {card_number}")
        else:
            print("✗ Nicht erkannt")


def example_5_manual_lookup():
    """
    Beispiel 5: Manueller Datenbankenlookup
    """
    print("\n" + "="*70)
    print("BEISPIEL 5: Manueller Datenbank-Lookup")
    print("="*70)

    # Lade Datenbank
    db = load_price_database()

    # Suche Kartennummern
    card_numbers_to_find = ["1", "80", "104", "136", "182"]

    for card_num in card_numbers_to_find:
        info = lookup_card_info(card_num, db)

        if info:
            print(f"{card_num:>3}: {info.get('name', 'N/A'):<30} "
                  f"({info.get('rarity', 'N/A'):<15}) "
                  f"€{info.get('trend', 0):.2f}")
        else:
            print(f"{card_num:>3}: NOT FOUND")


def example_6_json_output():
    """
    Beispiel 6: JSON-Output für Integration
    """
    print("\n" + "="*70)
    print("BEISPIEL 6: JSON-Output für externe Systeme")
    print("="*70)

    image_path = "live_1.png"

    result = process_image_full(image_path)

    # Output als JSON
    json_output = json.dumps(result, indent=2, ensure_ascii=False)
    print(json_output)

    # Für API/Webhooks
    if result["success"]:
        payload = {
            "card_id": result["number"],
            "card_name": result["name"],
            "rarity": result["rarity"],
            "current_price": result["price"],
            "source_image": result["image_path"]
        }
        print("\n✓ API Payload:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import sys

    examples = {
        "1": example_1_simple_ocr,
        "2": example_2_full_pipeline,
        "3": example_3_batch_processing,
        "4": example_4_custom_preprocessing,
        "5": example_5_manual_lookup,
        "6": example_6_json_output,
    }

    if len(sys.argv) > 1 and sys.argv[1] in examples:
        examples[sys.argv[1]]()
    else:
        print("""
Verfügbare Beispiele:

  python example_usage.py 1    - Einfache OCR
  python example_usage.py 2    - Vollständige Pipeline
  python example_usage.py 3    - Batch-Processing
  python example_usage.py 4    - Custom Preprocessing
  python example_usage.py 5    - Manueller Lookup
  python example_usage.py 6    - JSON-Output

Oder direkt als Modul importieren:
  from cards_ocr import extract_card_number, process_image_full
""")
