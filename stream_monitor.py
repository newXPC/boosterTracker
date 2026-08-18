#!/usr/bin/env python3
"""
Continuous stream monitor for Pokémon booster card recognition.
Takes screenshots, extracts card numbers via OCR, updates HTML artifact.
"""

import time
import json
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# Paths
BOOSTER_DIR = Path(__file__).parent
OCR_SCRIPT = BOOSTER_DIR / "cards_ocr.py"
PRICE_DB = BOOSTER_DIR / "sv10-preise.json"
HTML_FILE = BOOSTER_DIR / "booster-tracker.html"
SCREENSHOT_DIR = BOOSTER_DIR / "screenshots"

# Create screenshots directory
SCREENSHOT_DIR.mkdir(exist_ok=True)

# Configuration
NORMAL_INTERVAL = 4.0  # 4 seconds
FAST_INTERVAL = 0.5    # 0.5 seconds after card detection
FAST_MODE_DURATION = 20  # 20 seconds of fast mode

# Energy card patterns to skip
ENERGY_PATTERNS = [
    r'Feuer.*Energie',
    r'Fire.*Energy',
    r'Wasser.*Energie',
    r'Water.*Energy',
    r'Pflanze.*Energie',
    r'Grass.*Energy',
    r'Blitz.*Energie',
    r'Lightning.*Energy',
    r'Psycho.*Energie',
    r'Psychic.*Energy',
    r'Kampf.*Energie',
    r'Fighting.*Energy',
    r'Gift.*Energie',
    r'Poison.*Energy',
    r'Boden.*Energie',
    r'Ground.*Energy',
    r'Flug.*Energie',
    r'Flying.*Energy',
    r'Drachen.*Energie',
    r'Dragon.*Energy',
    r'Unlicht.*Energie',
    r'Darkness.*Energy',
    r'Metall.*Energie',
    r'Metal.*Energy',
    r'Fee.*Energie',
    r'Fairy.*Energy',
]

def load_price_db():
    """Load sv10-preise.json"""
    if not PRICE_DB.exists():
        print(f"❌ Price DB not found: {PRICE_DB}")
        return {}
    with open(PRICE_DB, 'r', encoding='utf-8') as f:
        return {card['number']: card for card in json.load(f)}

def is_energy_card(card_name):
    """Check if card is an energy card"""
    for pattern in ENERGY_PATTERNS:
        if re.search(pattern, card_name, re.IGNORECASE):
            return True
    return False

def take_screenshot(filename):
    """Take a screenshot of the lower half (camera input area)"""
    try:
        import mss
        from PIL import Image
        with mss.MSS() as sct:
            monitor = sct.monitors[1]  # Primary monitor

            # Capture only lower half (where camera/cards are)
            # Adjust these values based on your OBS layout
            monitor_height = monitor['height']
            camera_top = int(monitor_height * 0.4)  # Start at 40% down

            bounding_box = {
                'top': camera_top,
                'left': monitor['left'],
                'width': monitor['width'],
                'height': monitor_height - camera_top
            }

            screenshot = sct.grab(bounding_box)
            img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)

            # Upscale for better OCR (3x)
            new_size = (screenshot.size[0] * 3, screenshot.size[1] * 3)
            img = img.resize(new_size, Image.Resampling.LANCZOS)

            img.save(str(filename))
            return True
    except ImportError:
        print("❌ mss not installed. Install with: pip install mss pillow")
        return False
    except Exception as e:
        print(f"❌ Screenshot failed: {e}")
        return False

def extract_card_number_ocr(image_path):
    """Extract card number using cards_ocr.py"""
    if not OCR_SCRIPT.exists():
        print(f"❌ OCR script not found: {OCR_SCRIPT}")
        return None

    try:
        result = subprocess.run(
            [sys.executable, str(OCR_SCRIPT), str(image_path), "--json"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get('card_number')
    except subprocess.TimeoutExpired:
        pass  # OCR timeout, skip this screenshot
    except Exception as e:
        pass  # Silently skip errors

    return None

def lookup_card(card_number, price_db):
    """Lookup card in price database"""
    return price_db.get(card_number)

def update_html(cards_list, counters):
    """Update booster-tracker.html with new cards"""
    if not HTML_FILE.exists():
        print(f"❌ HTML file not found: {HTML_FILE}")
        return

    # Build card HTML
    cards_html = ""
    for i, card in enumerate(cards_list[:10]):  # Max 10 visible cards
        is_latest = (i == 0)
        latest_class = " latest" if is_latest else ""
        rarity_chip = card.get('rarity', 'Unknown')
        price = card.get('price', 'N/A')

        cards_html += f"""<div class="card{latest_class}">
  <p class="name">{card['name']}</p>
  <p class="set">Ewige Rivalen (DRI) · {card['number']}</p>
  <div class="row">
    <span class="chip">{rarity_chip}</span>
    <span class="price">~{price} €</span>
  </div>
</div>
"""

    # Build counters HTML
    counters_html = f"""<div class="counter c-sar"><div class="num">{counters.get('SAR', 0)}</div><div class="lbl">SAR</div></div>
  <div class="counter c-ir"><div class="num">{counters.get('IR', 0)}</div><div class="lbl">IR</div></div>
  <div class="counter c-fa"><div class="num">{counters.get('FA', 0)}</div><div class="lbl">FA</div></div>
  <div class="counter c-gold"><div class="num">{counters.get('Gold', 0)}</div><div class="lbl">Gold</div></div>
  <div class="counter c-ex"><div class="num">{counters.get('ex', 0)}</div><div class="lbl">ex</div></div>"""

    # Read existing HTML
    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # Replace counters
    html_content = re.sub(
        r'<div class="counters">.*?</div>',
        f'<div class="counters">\n  {counters_html}\n</div>',
        html_content,
        flags=re.DOTALL
    )

    # Replace cards section
    html_content = re.sub(
        r'<p class="display-label">.*?</p>.*?(?=<footer>)',
        f'<p class="display-label">Display 1 · aktuell</p>\n\n{cards_html}\n',
        html_content,
        flags=re.DOTALL
    )

    # Write updated HTML
    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)

def get_rarity_type(rarity_str):
    """Extract rarity type for counter increment"""
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
    print("🎥 Stream Monitor gestartet!")
    print(f"📁 Screenshot dir: {SCREENSHOT_DIR}")
    print(f"💾 HTML: {HTML_FILE}")
    print("Starte Screenshot-Loop...\n")

    price_db = load_price_db()
    print(f"✅ Preisdatenbank geladen: {len(price_db)} Karten\n")

    cards_list = []  # Most recent cards first
    counters = {'SAR': 0, 'IR': 0, 'FA': 0, 'Gold': 0, 'ex': 0}
    seen_cards = set()  # Prevent duplicates

    screenshot_count = 0
    last_card_time = 0
    interval = NORMAL_INTERVAL

    try:
        while True:
            screenshot_count += 1
            timestamp = datetime.now().strftime("%H:%M:%S")
            screenshot_file = SCREENSHOT_DIR / f"live_{screenshot_count}.png"

            # Take screenshot
            if not take_screenshot(screenshot_file):
                time.sleep(interval)
                continue

            # Extract card via OCR
            card_number = extract_card_number_ocr(screenshot_file)

            if card_number and card_number not in seen_cards:
                card_data = lookup_card(card_number, price_db)

                if card_data:
                    card_name = card_data.get('name', 'Unknown')

                    # Skip energy cards
                    if is_energy_card(card_name):
                        print(f"⚡ [{timestamp}] Energiekarte erkannt: {card_number} - übersprungen")
                    else:
                        # Add to tracking
                        seen_cards.add(card_number)
                        cards_list.insert(0, card_data)

                        # Update counters
                        rarity_type = get_rarity_type(card_data.get('rarity', ''))
                        if rarity_type:
                            counters[rarity_type] += 1

                        # Update HTML
                        update_html(cards_list, counters)

                        price = card_data.get('avg7', 'N/A')
                        print(f"✅ [{timestamp}] {card_number}: {card_name} (~{price}€)")

                        # Switch to fast mode
                        last_card_time = time.time()
                        interval = FAST_INTERVAL

            # Check if should return to normal interval
            if interval == FAST_INTERVAL:
                if time.time() - last_card_time > FAST_MODE_DURATION:
                    interval = NORMAL_INTERVAL
                    print(f"⏱️  [{timestamp}] Zurück zu normalem Tempo (4s)")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n⏹️  Stream Monitor gestoppt (Ctrl+C)")
        print(f"📊 Zusammenfassung: {len(seen_cards)} eindeutige Karten erkannt")
        print(f"   SAR: {counters['SAR']}, IR: {counters['IR']}, FA: {counters['FA']}, Gold: {counters['Gold']}, ex: {counters['ex']}")

if __name__ == '__main__':
    main()
