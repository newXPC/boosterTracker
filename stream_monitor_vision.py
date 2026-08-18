#!/usr/bin/env python3
"""
Stream monitor using Claude Vision for card detection.
Makes screenshots, sends to Claude API, gets card numbers back.
"""

import time
import json
import re
import subprocess
import sys
import base64
import os
from pathlib import Path
from datetime import datetime

import mss
from PIL import Image

# Import Anthropic API
try:
    from anthropic import Anthropic
except ImportError:
    print("Error: anthropic SDK not installed. Run: pip install anthropic")
    sys.exit(1)

# Paths
BOOSTER_DIR = Path(__file__).parent
PRICE_DB = BOOSTER_DIR / "sv10-preise.json"
HTML_FILE = BOOSTER_DIR / "booster-tracker.html"
SCREENSHOT_DIR = BOOSTER_DIR / "screenshots"

SCREENSHOT_DIR.mkdir(exist_ok=True)

# Configuration
NORMAL_INTERVAL = 4.0
FAST_INTERVAL = 0.5
FAST_MODE_DURATION = 20

# Energy card patterns
ENERGY_PATTERNS = [
    'Feuer', 'Fire', 'Wasser', 'Water', 'Pflanze', 'Grass',
    'Blitz', 'Lightning', 'Psycho', 'Psychic', 'Kampf', 'Fighting',
    'Gift', 'Poison', 'Boden', 'Ground', 'Flug', 'Flying',
    'Drachen', 'Dragon', 'Unlicht', 'Darkness', 'Metall', 'Metal',
    'Fee', 'Fairy', 'Energie', 'Energy'
]

def load_price_db():
    if not PRICE_DB.exists():
        print(f"Fehler: {PRICE_DB} nicht gefunden")
        return {}
    with open(PRICE_DB, 'r', encoding='utf-8') as f:
        return {card['number']: card for card in json.load(f)}

def is_energy_card(card_name):
    for pattern in ENERGY_PATTERNS:
        if pattern.lower() in card_name.lower():
            return True
    return False

def take_screenshot(filename):
    """Capture the Camo window area"""
    try:
        with mss.MSS() as sct:
            monitor = sct.monitors[1]
            region = {
                'top': int(monitor['height'] * 0.1),
                'left': int(monitor['width'] * 0.2),
                'width': int(monitor['width'] * 0.6),
                'height': int(monitor['height'] * 0.8)
            }
            screenshot = sct.grab(region)
            img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
            img.save(str(filename))
            return True
    except Exception as e:
        print(f"Screenshot Error: {e}")
        return False

def encode_image_to_base64(image_path):
    """Encode image to base64 for API"""
    with open(image_path, 'rb') as f:
        return base64.standard_b64encode(f.read()).decode('utf-8')

def detect_cards_with_vision(client, image_path):
    """Send screenshot to Claude Vision, get card number back"""
    try:
        image_data = encode_image_to_base64(image_path)

        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": """Look at this Pokemon card image.
                            If you see a Pokemon card, extract the card number in format XXX/YYY (e.g. "080/182").
                            ONLY respond with the card number, nothing else.
                            If no card is visible, respond with: NONE
                            """
                        }
                    ],
                }
            ],
        )

        result = message.content[0].text.strip()

        # Check if valid card number format
        if result != "NONE" and re.match(r'\d{1,3}/\d{1,3}', result):
            return result
        return None

    except Exception as e:
        print(f"Vision API error: {e}")
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
        rarity = card.get('rarity', 'Unknown')
        price = card.get('avg7', 'N/A')

        cards_html += f"""<div class="card{latest_class}">
  <p class="name">{card['name']}</p>
  <p class="set">Ewige Rivalen (DRI) · {card['number']}</p>
  <div class="row">
    <span class="chip">{rarity}</span>
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
    elif 'gold' in rarity_str:
        return 'Gold'
    elif 'ex' in rarity_str:
        return 'ex'
    return None

def main():
    # Check API key
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        print("Example: set ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    client = Anthropic(api_key=api_key)

    print("=" * 60)
    print("BOOSTER TRACKER - VISION MODE")
    print("=" * 60)
    print("Using Claude Vision for card detection")
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

            if not take_screenshot(screenshot_file):
                time.sleep(interval)
                continue

            card_number = detect_cards_with_vision(client, str(screenshot_file))

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
