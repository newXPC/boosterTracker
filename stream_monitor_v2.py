#!/usr/bin/env python3
"""
Optimized stream monitor for fullscreen OBS.
- Captures bottom-left card number area only
- 3x upscaling + CLAHE preprocessing
- GPU acceleration when available
- Very frequent screenshots (0.2s)
"""

import time
import json
import re
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np
from PIL import Image
import mss

# Paths
BOOSTER_DIR = Path(__file__).parent
OCR_SCRIPT = BOOSTER_DIR / "cards_ocr.py"
PRICE_DB = BOOSTER_DIR / "sv10-preise.json"
HTML_FILE = BOOSTER_DIR / "booster-tracker.html"
SCREENSHOT_DIR = BOOSTER_DIR / "screenshots"

SCREENSHOT_DIR.mkdir(exist_ok=True)

# Configuration
NORMAL_INTERVAL = 4.0
FAST_INTERVAL = 0.2  # Very fast after card detected
FAST_MODE_DURATION = 20

# GPU check
try:
    import torch
    GPU_AVAILABLE = torch.cuda.is_available()
    GPU_NAME = torch.cuda.get_device_name(0) if GPU_AVAILABLE else "CPU"
except:
    GPU_AVAILABLE = False
    GPU_NAME = "CPU"

# Energy card patterns to skip
ENERGY_PATTERNS = [
    r'Feuer.*Energie|Fire.*Energy',
    r'Wasser.*Energie|Water.*Energy',
    r'Pflanze.*Energie|Grass.*Energy',
    r'Blitz.*Energie|Lightning.*Energy',
    r'Psycho.*Energie|Psychic.*Energy',
    r'Kampf.*Energie|Fighting.*Energy',
    r'Gift.*Energie|Poison.*Energy',
    r'Boden.*Energie|Ground.*Energy',
    r'Flug.*Energie|Flying.*Energy',
    r'Drachen.*Energie|Dragon.*Energy',
    r'Unlicht.*Energie|Darkness.*Energy',
    r'Metall.*Energie|Metal.*Energy',
    r'Fee.*Energie|Fairy.*Energy',
]

def load_price_db():
    if not PRICE_DB.exists():
        print(f"Fehler: {PRICE_DB} nicht gefunden")
        return {}
    with open(PRICE_DB, 'r', encoding='utf-8') as f:
        return {card['number']: card for card in json.load(f)}

def is_energy_card(card_name):
    for pattern in ENERGY_PATTERNS:
        if re.search(pattern, card_name, re.IGNORECASE):
            return True
    return False

def preprocess_image(image_path, upscale=3):
    """Load and preprocess image for OCR"""
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        return None

    # Upscale
    new_height = img.shape[0] * upscale
    new_width = img.shape[1] * upscale
    img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)

    # CLAHE (Contrast Limited Adaptive Histogram Equalization)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    img = cv2.merge([l, a, b])
    img = cv2.cvtColor(img, cv2.COLOR_LAB2BGR)

    # Denoise
    img = cv2.fastNlMeansDenoisingColored(img, None, h=10, hForColorComponents=10, templateWindowSize=7, searchWindowSize=21)

    # Convert to RGB for PIL
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return Image.fromarray(img_rgb)

def take_screenshot_card_area(filename):
    """Capture the entire Camo window card display area"""
    try:
        with mss.MSS() as sct:
            monitor = sct.monitors[1]

            # Capture FULL Camo window (centered, where cards are shown)
            # Much larger region to ensure we catch the card
            region = {
                'top': int(monitor['height'] * 0.1),      # 10% from top
                'left': int(monitor['width'] * 0.2),      # 20% from left
                'width': int(monitor['width'] * 0.6),     # 60% of width
                'height': int(monitor['height'] * 0.8)    # 80% of height
            }

            screenshot = sct.grab(region)
            img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
            img.save(str(filename))
            return True
    except Exception as e:
        print(f"Screenshot Fehler: {e}")
        return False

def extract_card_number_ocr(image_path):
    """Extract card number using cards_ocr.py with GPU if available"""
    if not OCR_SCRIPT.exists():
        return None

    try:
        cmd = [sys.executable, str(OCR_SCRIPT), str(image_path), "--json"]
        if GPU_AVAILABLE:
            cmd.append("--gpu")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get('card_number')
    except:
        pass
    return None

def lookup_card(card_number, price_db):
    return price_db.get(card_number)

def update_html(cards_list, counters):
    if not HTML_FILE.exists():
        return

    cards_html = ""
    for i, card in enumerate(cards_list[:10]):
        is_latest = (i == 0)
        latest_class = " latest" if is_latest else ""
        rarity_chip = card.get('rarity', 'Unknown')
        price = card.get('avg7', 'N/A')

        cards_html += f"""<div class="card{latest_class}">
  <p class="name">{card['name']}</p>
  <p class="set">Ewige Rivalen (DRI) · {card['number']}</p>
  <div class="row">
    <span class="chip">{rarity_chip}</span>
    <span class="price">~{price} EUR</span>
  </div>
</div>
"""

    counters_html = f"""<div class="counter c-sar"><div class="num">{counters.get('SAR', 0)}</div><div class="lbl">SAR</div></div>
  <div class="counter c-ir"><div class="num">{counters.get('IR', 0)}</div><div class="lbl">IR</div></div>
  <div class="counter c-fa"><div class="num">{counters.get('FA', 0)}</div><div class="lbl">FA</div></div>
  <div class="counter c-gold"><div class="num">{counters.get('Gold', 0)}</div><div class="lbl">Gold</div></div>
  <div class="counter c-ex"><div class="num">{counters.get('ex', 0)}</div><div class="lbl">ex</div></div>"""

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html_content = f.read()

    html_content = re.sub(
        r'<div class="counters">.*?</div>',
        f'<div class="counters">\n  {counters_html}\n</div>',
        html_content,
        flags=re.DOTALL
    )

    html_content = re.sub(
        r'<p class="display-label">.*?</p>.*?(?=<footer>)',
        f'<p class="display-label">Display 1 · aktuell</p>\n\n{cards_html}\n',
        html_content,
        flags=re.DOTALL
    )

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)

def get_rarity_type(rarity_str):
    rarity_str = str(rarity_str).lower()
    if 'special art' in rarity_str or 'sar' in rarity_str:
        return 'SAR'
    elif 'illustration' in rarity_str or 'ir' in rarity_str:
        return 'IR'
    elif 'full art' in rarity_str or 'fa' in rarity_str:
        return 'FA'
    elif 'gold' in rarity_str or 'golden' in rarity_str:
        return 'Gold'
    elif 'ex' in rarity_str:
        return 'ex'
    return None

def main():
    print("=" * 60)
    print("BOOSTER TRACKER v2 - GPU OPTIMIZED")
    print("=" * 60)
    print(f"Processing: {GPU_NAME}")
    print(f"Screenshot dir: {SCREENSHOT_DIR}")
    print()

    price_db = load_price_db()
    print(f"Preisdatenbank: {len(price_db)} Karten")
    print()

    cards_list = []
    counters = {'SAR': 0, 'IR': 0, 'FA': 0, 'Gold': 0, 'ex': 0}
    seen_cards = set()

    screenshot_count = 0
    last_card_time = 0
    interval = NORMAL_INTERVAL

    try:
        while True:
            screenshot_count += 1
            timestamp = datetime.now().strftime("%H:%M:%S")
            screenshot_file = SCREENSHOT_DIR / f"live_{screenshot_count}.png"

            if not take_screenshot_card_area(screenshot_file):
                time.sleep(interval)
                continue

            card_number = extract_card_number_ocr(screenshot_file)

            if card_number and card_number not in seen_cards:
                card_data = lookup_card(card_number, price_db)

                if card_data:
                    card_name = card_data.get('name', 'Unknown')

                    if is_energy_card(card_name):
                        print(f"[{timestamp}] Energie -> skip")
                    else:
                        seen_cards.add(card_number)
                        cards_list.insert(0, card_data)
                        rarity_type = get_rarity_type(card_data.get('rarity', ''))
                        if rarity_type:
                            counters[rarity_type] += 1

                        update_html(cards_list, counters)
                        price = card_data.get('avg7', 'N/A')
                        print(f"[{timestamp}] FOUND: {card_number} {card_name} (~{price}EUR)")

                        last_card_time = time.time()
                        interval = FAST_INTERVAL

            if interval == FAST_INTERVAL:
                if time.time() - last_card_time > FAST_MODE_DURATION:
                    interval = NORMAL_INTERVAL
                    print(f"[{timestamp}] Back to normal (4s)")

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\nStopped. Found: {len(seen_cards)} cards")
        print(f"SAR: {counters['SAR']}, IR: {counters['IR']}, FA: {counters['FA']}, Gold: {counters['Gold']}, ex: {counters['ex']}")

if __name__ == '__main__':
    main()
