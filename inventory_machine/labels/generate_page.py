# generate_page.py (or your main script)
from qrcode import generate_qr_for_sticker
from PIL import Image

# 8.5x11
sheet_width_inches = 8.5
sheet_height_inches = 11.0
sticker_width_inches = 0.5
sticker_height_inches = 0.5

# Number of stickers per row/column (adjust to fit sheet)
sticker_count_per_row = 10          # e.g., 10 stickers across the top of the sheet
sticker_count_per_column = 8        # e.g., 8 rows → 8×10 = 80 stickers
total_stickers = sticker_count_per_row * sticker_count_per_column

# Create a blank canvas for the full page (8.5" × 11" at 300 DPI = 2550 × 3300 pixels)
page_width_px = round(sheet_width_inches * 300)
page_height_px = round(sheet_height_inches * 300)
page_img = Image.new("RGB", (page_width_px, page_height_px), "white")

# For each sticker, generate its QR code (using qrcode.py) and place it on the page
for row in range(sticker_count_per_column):
    for col in range(sticker_count_per_row):
        sticker_idx = row * sticker_count_per_row + col + 1  # 1-based index
        # Example data per sticker (customize as needed)
        sticker_data = f"Sticker {sticker_idx} on {row+1},{col+1}"
        
        # Generate QR image (128x128 px = .5" size)
        qr_path = f"temp_sticker_{sticker_idx}.png"
        generate_qr_for_sticker(sticker_data, qr_path)
        
        # Load the generated QR image
        qr_img = Image.open(qr_path).convert("RGBA")
        
        # Calculate placement on the page (in pixels)
        # Each sticker occupies ~0.5" × 0.5" = 150 × 150 px at 300 DPI
        sticker_px_w = round(sticker_width_inches * 300)
        sticker_px_h = round(sticker_height_inches * 300)
        
        # Position (left/top of page)
        x = round(col * (sticker_px_w + 0.1))  # small gap between stickers
        y = round(row * (sticker_px_h + 0.1))  # small gap between rows
        
        # Paste QR onto page canvas (top-left corner of sticker)
        page_img.paste(qr_img, (x, y), qr_img)

# Save the full printable page
page_img.save("8.5x11_sticker_page.png")
print("Full printable page saved as '8.5x11_sticker_page.png'")

# Clean up temporary QR files (optional)
import os
for fname in os.listdir("."):
    if fname.endswith(".png") and fname != "8.5x11_sticker_page.png":
        os.remove(fname)