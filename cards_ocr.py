"""
EasyOCR-basierte Kartennummern-Extraktion für Pokémon-Screenshots
Pipeline: Preprocessing -> OCR -> Kartenlookup
"""

import re
import json
import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any
import numpy as np
import cv2
from PIL import Image, ImageEnhance

# EasyOCR import (lazy-loaded bei Bedarf)
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    print("⚠️  EasyOCR nicht installiert. Bitte installieren: pip install easyocr")

# ============================================================================
# LOGGING SETUP
# ============================================================================

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# ============================================================================
# GLOBALER OCR READER (singleton pattern)
# ============================================================================

_ocr_reader = None


def get_ocr_reader(languages=['de', 'en'], gpu=False):
    """
    Lazy-Loader für EasyOCR Reader (einmalig pro Session).

    Args:
        languages: Liste von Sprach-Codes (default: Deutsch + Englisch)
        gpu: True wenn GPU verfügbar, False für CPU

    Returns:
        easyocr.Reader Objekt
    """
    global _ocr_reader

    if _ocr_reader is None:
        if not EASYOCR_AVAILABLE:
            raise ImportError("EasyOCR ist nicht installiert. "
                            "Bitte ausführen: pip install easyocr")

        logger.info(f"Lade EasyOCR Reader für Sprachen: {languages}")
        _ocr_reader = easyocr.Reader(
            languages,
            gpu=gpu,
            verbose=False,
            quantize=True  # Schneller mit quantisierten Modellen
        )
        logger.info("✓ OCR Reader geladen")

    return _ocr_reader


# ============================================================================
# IMAGE PREPROCESSING
# ============================================================================

def crop_card_number_region(image: np.ndarray,
                            box_h_range=(0.75, 1.0),
                            box_w_range=(0.0, 0.25)) -> Optional[np.ndarray]:
    """
    Crop die Kartennummern-Region (untere LINKS) aus dem Bild.

    Die Kartennummern befinden sich typischerweise in der unteren LINKEN Ecke
    eines Pokémon-Kartenfotos. Diese Funktion extrahiert diese Region flexibel
    basierend auf Prozentsätzen der Bilddimensionen.

    Args:
        image: Input-Bild als numpy array (BGR oder RGB)
        box_h_range: Tuple (start_pct, end_pct) für Höhe (default: untere 25%)
        box_w_range: Tuple (start_pct, end_pct) für Breite (default: rechte 20%)

    Returns:
        Cropped Bild oder None wenn ungültig
    """
    if image is None or image.size == 0:
        logger.warning("Ungültiges Input-Bild für crop_card_number_region")
        return None

    h, w = image.shape[:2]

    # Berechne Pixel-Grenzen
    y_start = int(h * box_h_range[0])
    y_end = int(h * box_h_range[1])
    x_start = int(w * box_w_range[0])
    x_end = int(w * box_w_range[1])

    cropped = image[y_start:y_end, x_start:x_end]
    logger.debug(f"Crop: ({x_start}, {y_start}) -> ({x_end}, {y_end}), "
                f"Größe: {cropped.shape}")

    return cropped


def preprocess_for_ocr(image: np.ndarray, upscale_factor=2) -> np.ndarray:
    """
    Preprocessing-Pipeline für bessere OCR-Ergebnisse:
    1. Graustufen-Konversion
    2. Kontrast/Helligkeit-Normalisierung (CLAHE)
    3. Bilinear Upscaling
    4. Threshold (optional für sehr kleine Text)

    Args:
        image: Input-Bild
        upscale_factor: Skalierungsfaktor (2-3x empfohlen)

    Returns:
        Verarbeitetes Bild
    """
    if image is None or image.size == 0:
        logger.warning("Ungültiges Input-Bild für preprocess_for_ocr")
        return image

    # 1. Graustufen
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    logger.debug(f"Step 1 - Graustufen: shape={gray.shape}")

    # 2. CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    logger.debug("Step 2 - CLAHE angewandt")

    # 3. Bilinear Upscaling für bessere OCR
    h, w = enhanced.shape
    target_w = int(w * upscale_factor)
    target_h = int(h * upscale_factor)
    upscaled = cv2.resize(enhanced, (target_w, target_h),
                         interpolation=cv2.INTER_LINEAR)
    logger.debug(f"Step 3 - Upscaled: {enhanced.shape} -> {upscaled.shape}")

    # 4. Leichte Denoising
    denoised = cv2.fastNlMeansDenoising(upscaled, h=10, templateWindowSize=7,
                                        searchWindowSize=21)
    logger.debug("Step 4 - Denoise angewandt")

    return denoised


def extract_text_from_region(image: np.ndarray, reader=None) -> str:
    """
    Führt EasyOCR auf der Kartennummern-Region durch.
    Speichert alle Text-Boxen für einzelne Pattern-Suche.

    Args:
        image: Preprocessing-Bild
        reader: EasyOCR Reader (wird geladen wenn None)

    Returns:
        Erkannter Text und alle OCR-Boxen
    """
    if reader is None:
        reader = get_ocr_reader()

    results = reader.readtext(image, detail=1)

    # Kombiniere auch für Logging
    texts = [text for (bbox, text, confidence) in results]
    combined_text = ' '.join(texts)

    logger.debug(f"OCR Results ({len(results)} Fragmente): {combined_text}")
    return combined_text, results


# ============================================================================
# KARTENNUMMER-EXTRAKTION MIT REGEX & FALLBACK
# ============================================================================

def extract_card_number_from_text(text: str) -> Optional[str]:
    """
    Extrahiert Kartennummern aus OCR-Text.

    Zielformat: "XXX/YYY" (z.B. "80/182")
    - Robustheit gegen OCR-Fehler (O->0, l->1, etc.)

    Args:
        text: OCR-erkannter Text

    Returns:
        Kartennummer als String (z.B. "80/182") oder None
    """
    # Normalize häufige OCR-Fehler
    normalized = text.replace('O', '0').replace('l', '1').replace('I', '1').replace('S', '5')
    logger.debug(f"Normalized text: {normalized}")

    # Pattern: (1-3 Ziffern) / (1-3 Ziffern)
    pattern = r'(\d{1,3})\s*/\s*(\d{1,3})'
    matches = re.findall(pattern, normalized)

    if matches:
        card_num = f"{matches[0][0]}/{matches[0][1]}"
        logger.info(f"✓ Kartennummer gefunden: {card_num}")
        return card_num

    return None


def extract_card_number_from_ocr_results(ocr_results: list) -> Optional[str]:
    """
    Durchsuche JEDEN erkannten Text-Fragment nach XXX/YYY Pattern.
    Robuster als kombinierter Text.

    Args:
        ocr_results: Liste von (bbox, text, confidence) Tuples von EasyOCR

    Returns:
        Kartennummer oder None
    """
    logger.debug(f"Suche nach Kartennummer in {len(ocr_results)} Text-Fragmenten...")

    for bbox, text, confidence in ocr_results:
        card_num = extract_card_number_from_text(text)
        if card_num:
            logger.info(f"✓ Kartennummer in Fragment gefunden: {card_num} (conf={confidence:.2f})")
            return card_num

    logger.warning("Keine Kartennummer in OCR-Fragmenten gefunden")
    return None


def extract_card_number(image_path: str,
                       upscale_factor: int = 2,
                       gpu: bool = False) -> Optional[str]:
    """
    Hauptfunktion: Kartennummer aus Screenshot extrahieren.

    Pipeline:
    1. Bild laden
    2. Kartennummern-Region cropen
    3. Preprocessing (CLAHE, Upscaling, Denoise)
    4. OCR durchführen
    5. Regex-basierte Extraktion

    Args:
        image_path: Pfad zum Screenshot
        upscale_factor: Upscaling-Faktor (2-3)
        gpu: GPU-Beschleunigung nutzen

    Returns:
        Kartennummer als String ("80/182") oder None bei Fehler
    """
    # 0. Bild laden
    if not Path(image_path).exists():
        logger.error(f"Bild nicht gefunden: {image_path}")
        return None

    image = cv2.imread(image_path)
    if image is None:
        logger.error(f"Konnte Bild nicht laden: {image_path}")
        return None

    logger.info(f"Lade Bild: {image_path} ({image.shape})")

    # 1. Crop Kartennummern-Region
    cropped = crop_card_number_region(image)
    if cropped is None:
        logger.error("Konnte Kartennummern-Region nicht cropen")
        return None

    # 2. Preprocessing
    processed = preprocess_for_ocr(cropped, upscale_factor=upscale_factor)

    # 3. OCR
    reader = get_ocr_reader(gpu=gpu)
    text, results = extract_text_from_region(processed, reader)

    if not results:
        logger.warning("OCR hat keinen Text erkannt")
        return None

    # 4. Kartennummer extrahieren (durchsuche JEDEN Fragment nach XXX/YYY)
    card_number = extract_card_number_from_ocr_results(results)

    return card_number


# ============================================================================
# JSON LOOKUP & ERGEBNIS-ZUSAMMENSTELLUNG
# ============================================================================

def load_price_database(json_path: str = None) -> Dict[str, Any]:
    """
    Lädt die sv10-preise.json Datei.

    Args:
        json_path: Pfad zur JSON-Datei. Default: BoosterTracker/sv10-preise.json

    Returns:
        Dict mit Kartennummern als Keys
    """
    if json_path is None:
        # Suche im aktuellen Verzeichnis und Parent-Verzeichnis
        possible_paths = [
            Path(__file__).parent / "sv10-preise.json",
            Path(__file__).parent.parent / "sv10-preise.json",
            Path.cwd() / "sv10-preise.json"
        ]
        json_path = next((p for p in possible_paths if p.exists()), None)

        if json_path is None:
            logger.warning("sv10-preise.json nicht gefunden. "
                         "Lookup wird übersprungen.")
            return {}

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Index nach Kartennummer
        db = {item['number']: item for item in data}
        logger.info(f"✓ {len(db)} Karten aus {json_path} geladen")
        return db

    except Exception as e:
        logger.error(f"Fehler beim Laden von {json_path}: {e}")
        return {}


def lookup_card_info(card_number: str,
                    price_db: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Lookup Kartendetails in der Preisdatenbank.

    Args:
        card_number: Kartennummer ("80/182")
        price_db: Geladene Preisdatenbank (wird geladen wenn None)

    Returns:
        Dict mit {number, name, rarity, price (trend), ...}
        oder leerer Dict wenn nicht gefunden
    """
    if price_db is None:
        price_db = load_price_database()

    # Kartennummern in DB sind als Strings gespeichert, aber manchmal
    # nur die erste Komponente (z.B. "80" statt "80/182")
    card_base = card_number.split('/')[0] if '/' in card_number else card_number

    if card_number in price_db:
        return price_db[card_number]
    elif card_base in price_db:
        return price_db[card_base]
    else:
        logger.warning(f"Kartennummer {card_number} nicht in Datenbank")
        return {}


def process_image_full(image_path: str,
                      return_debug_info: bool = False) -> Dict[str, Any]:
    """
    Vollständige Pipeline: OCR -> Lookup -> JSON Output

    Args:
        image_path: Pfad zum Screenshot
        return_debug_info: True um auch OCR Details zu return

    Returns:
        {
            "success": bool,
            "number": "80/182" oder None,
            "name": "...",
            "rarity": "...",
            "price": float (trend),
            "image_path": "...",
            "error": "..." (nur bei Fehler)
        }
    """
    result = {
        "success": False,
        "number": None,
        "name": None,
        "rarity": None,
        "price": None,
        "image_path": str(image_path),
        "error": None
    }

    try:
        # OCR
        card_number = extract_card_number(image_path)

        if not card_number:
            result["error"] = "Kartennummer konnte nicht erkannt werden"
            return result

        result["number"] = card_number

        # Lookup
        price_db = load_price_database()
        card_info = lookup_card_info(card_number, price_db)

        if card_info:
            result["success"] = True
            result["name"] = card_info.get("name")
            result["rarity"] = card_info.get("rarity")
            result["price"] = card_info.get("trend")  # Oder avg7, avg30 je nach Bedarf
        else:
            result["success"] = False
            result["error"] = f"Karte {card_number} nicht in Datenbank"

    except Exception as e:
        result["error"] = str(e)
        logger.exception(f"Fehler bei Bildverarbeitung: {e}")

    return result


# ============================================================================
# CLI & MAIN
# ============================================================================

def main():
    """
    CLI-Interface für cards_ocr.py

    Nutzung:
        python cards_ocr.py <image_path> [--gpu] [--no-lookup]
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Pokémon-Kartennummern-Extraktion mit EasyOCR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python cards_ocr.py live_1.png
  python cards_ocr.py live_1.png --json
  python cards_ocr.py live_1.png --gpu --verbose
        """
    )

    parser.add_argument("image", help="Pfad zum Screenshot")
    parser.add_argument("--json", action="store_true",
                       help="JSON-Output (default: Pretty-Print)")
    parser.add_argument("--gpu", action="store_true",
                       help="GPU-Beschleunigung nutzen (wenn verfügbar)")
    parser.add_argument("--no-lookup", action="store_true",
                       help="Nur OCR, kein Datenbankenlookup")
    parser.add_argument("--upscale", type=int, default=2,
                       help="Upscaling-Faktor (default: 2)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose Logging")

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    # Verarbeite Bild
    if args.no_lookup:
        # Nur OCR
        card_number = extract_card_number(args.image,
                                         upscale_factor=args.upscale,
                                         gpu=args.gpu)
        if card_number:
            if args.json:
                print(json.dumps({"number": card_number}, indent=2))
            else:
                print(f"Kartennummer: {card_number}")
            sys.exit(0)
        else:
            if args.json:
                print(json.dumps({"error": "Kartennummer nicht erkannt"}, indent=2))
            else:
                print("Fehler: Kartennummer nicht erkannt")
            sys.exit(1)
    else:
        # Vollständige Pipeline
        result = process_image_full(args.image)

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            if result["success"]:
                print(f"""
Kartennummer:  {result['number']}
Name:          {result['name']}
Seltenheit:    {result['rarity']}
Preis (Trend): €{result['price']:.2f}
""")
            else:
                print(f"Fehler: {result.get('error', 'Unbekannter Fehler')}")

        sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
