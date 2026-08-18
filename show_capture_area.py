#!/usr/bin/env python3
"""Show what area the script is capturing"""

import mss
from PIL import Image, ImageDraw
from pathlib import Path

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

print("Erfasse den Screenshot-Bereich...")

with mss.MSS() as sct:
    monitor = sct.monitors[1]

    print(f"Monitor Auflösung: {monitor['width']}x{monitor['height']}")

    # Current capture region (bottom-left)
    region = {
        'top': monitor['height'] - 600,
        'left': monitor['left'] + 100,
        'width': 500,
        'height': 500
    }

    print(f"Capture area: top={region['top']}, left={region['left']}, {region['width']}x{region['height']}")
    print()

    # Take screenshot of region
    screenshot = sct.grab(region)
    img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)

    # Save
    output_file = SCREENSHOT_DIR / "capture_area_demo.png"
    img.save(str(output_file))
    print(f"Screenshot gespeichert: {output_file}")
    print()
    print("Oeffne diese Datei und pruefe ob die Kartennummern darin sichtbar sind!")
    print()
    print("Falls NICHT, sag mir wo die Kartennummern sind im Stream:")
    print("  - Oben/Mitte/Unten?")
    print("  - Links/Mitte/Rechts?")
    print("  - Wie gross sind sie?")
