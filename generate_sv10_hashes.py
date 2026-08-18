#!/usr/bin/env python3
"""
Generate image hashes for all SV10 (Ewige Rivalen) cards.
Downloads card images from Pokemon TCG API and creates hash database.
"""

import json
import requests
import imagehash
from PIL import Image
from io import BytesIO
from pathlib import Path
import time

# Load sv10-preise.json
PRICE_DB_PATH = "sv10-preise.json"
CARDS_DIR = Path("sv10_cards_images")
HASHES_DB = "sv10_hashes.json"

CARDS_DIR.mkdir(exist_ok=True)

def load_card_list():
    """Load cards from sv10-preise.json"""
    with open(PRICE_DB_PATH, 'r', encoding='utf-8') as f:
        cards = json.load(f)
    return {card['number']: card for card in cards}

def download_card_image(card_number):
    """Download card image directly from images.pokemontcg.io"""
    try:
        # Direct image URL: https://images.pokemontcg.io/sv10/{number}.png
        num = int(str(card_number).split('/')[0])
        image_url = f"https://images.pokemontcg.io/sv10/{num}.png"

        img_response = requests.get(image_url, timeout=10)
        if img_response.status_code == 200:
            return Image.open(BytesIO(img_response.content))
    except Exception:
        pass

    return None

def generate_hashes(image):
    """Generate 4 different hashes from image"""
    return {
        'average': str(imagehash.average_hash(image)),
        'whash': str(imagehash.whash(image)),
        'phash': str(imagehash.phash(image)),
        'dhash': str(imagehash.dhash(image))
    }

def main():
    print("=" * 60)
    print("SV10 HASH GENERATOR")
    print("=" * 60)
    print()

    cards = load_card_list()
    print(f"Loaded {len(cards)} cards from sv10-preise.json")
    print()

    hashes_db = {}
    success_count = 0
    fail_count = 0

    for i, (card_num, card_info) in enumerate(cards.items(), 1):
        print(f"[{i}/{len(cards)}] {card_num}: {card_info['name']}", end=" ... ")

        # Download image
        image = download_card_image(card_num)

        if image:
            # Generate hashes
            hashes = generate_hashes(image)
            hashes_db[card_num] = {
                'name': card_info['name'],
                'rarity': card_info.get('rarity', 'Unknown'),
                'hashes': hashes
            }

            # Save image
            img_path = CARDS_DIR / f"{card_num}.png"
            image.save(str(img_path))

            print("✓")
            success_count += 1
        else:
            print("✗ (failed to download)")
            fail_count += 1

        # Rate limit
        time.sleep(0.1)

    # Save hashes database
    print()
    print(f"Saving hashes database...")
    with open(HASHES_DB, 'w', encoding='utf-8') as f:
        json.dump(hashes_db, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print(f"Success: {success_count}/{len(cards)}")
    print(f"Failed: {fail_count}/{len(cards)}")
    print(f"Hashes saved to: {HASHES_DB}")
    print(f"Images saved to: {CARDS_DIR}")
    print("=" * 60)

if __name__ == '__main__':
    main()
