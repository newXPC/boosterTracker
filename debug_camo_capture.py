#!/usr/bin/env python3
"""Debug: Show exactly what regions are being captured"""

import mss
from PIL import Image, ImageDraw
from pathlib import Path

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

with mss.MSS() as sct:
    monitor = sct.monitors[1]
    print(f"Monitor: {monitor['width']}x{monitor['height']}")
    print()

    # Full monitor screenshot
    print("1. Capturing FULL monitor...")
    full = sct.grab(monitor)
    full_img = Image.frombytes('RGB', full.size, full.rgb)
    full_img.save(str(SCREENSHOT_DIR / "00_full_monitor.png"))
    print(f"   Saved: 00_full_monitor.png")

    # Current region (from stream_monitor_v2.py)
    region = {
        'top': int(monitor['height'] * 0.2),
        'left': int(monitor['width'] * 0.3),
        'width': int(monitor['width'] * 0.4),
        'height': int(monitor['height'] * 0.6)
    }

    print()
    print("2. Current capture region:")
    print(f"   top={region['top']}, left={region['left']}")
    print(f"   {region['width']}x{region['height']}")

    current = sct.grab(region)
    current_img = Image.frombytes('RGB', current.size, current.rgb)
    current_img.save(str(SCREENSHOT_DIR / "01_current_region.png"))
    print(f"   Saved: 01_current_region.png")

    print()
    print("3. Oeffne beide Screenshots und vergleiche:")
    print("   - 00_full_monitor.png (zeigt ganzen Desktop)")
    print("   - 01_current_region.png (was das Script captured)")
    print()
    print("   Falls Kartennummern in 00 aber NICHT in 01 -> Bereich muss angepasst werden!")
    print()
    print("   Sag mir dann: Wo sind die Kartennummern im vollen Screenshot?")
