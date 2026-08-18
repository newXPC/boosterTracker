#!/usr/bin/env python3
"""Debug OCR pipeline - show each step"""

import cv2
import numpy as np
from pathlib import Path

image_path = "screenshots/live_2.png"
output_dir = Path("debug_ocr_output")
output_dir.mkdir(exist_ok=True)

# Load image
img = cv2.imread(image_path)
print(f"1. Original: {img.shape}")
cv2.imwrite(str(output_dir / "01_original.png"), img)

# Crop bottom-left (0-25% width, 75-100% height)
h, w = img.shape[:2]
y_start = int(h * 0.75)
y_end = int(h * 1.0)
x_start = int(w * 0.0)
x_end = int(w * 0.25)

cropped = img[y_start:y_end, x_start:x_end]
print(f"2. Cropped (bottom-left): {cropped.shape}")
cv2.imwrite(str(output_dir / "02_cropped.png"), cropped)

# Upscale 3x
upscale = 3
new_h, new_w = cropped.shape[0] * upscale, cropped.shape[1] * upscale
upscaled = cv2.resize(cropped, (int(new_w), int(new_h)), interpolation=cv2.INTER_LANCZOS4)
print(f"3. Upscaled 3x: {upscaled.shape}")
cv2.imwrite(str(output_dir / "03_upscaled.png"), upscaled)

# CLAHE
lab = cv2.cvtColor(upscaled, cv2.COLOR_BGR2LAB)
l, a, b = cv2.split(lab)
clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
l = clahe.apply(l)
clahe_img = cv2.merge([l, a, b])
clahe_img = cv2.cvtColor(clahe_img, cv2.COLOR_LAB2BGR)
print(f"4. CLAHE applied: {clahe_img.shape}")
cv2.imwrite(str(output_dir / "04_clahe.png"), clahe_img)

# Denoise
denoised = cv2.fastNlMeansDenoising(clahe_img, h=10, templateWindowSize=7, searchWindowSize=21)
print(f"5. Denoised: {denoised.shape}")
cv2.imwrite(str(output_dir / "05_denoised.png"), denoised)

print()
print(f"Debug outputs saved to: {output_dir}")
print("Check these files to see what OCR receives!")
