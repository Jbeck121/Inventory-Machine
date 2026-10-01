# qrcode.py
# Generates a QR code sized for .5" x .5" stickers (≈127x127 pixels at 300 DPI).
# Uses standard QR library; requires: pip install qrcode[pil]

import qrcode
from PIL import Image

def generate_qr_for_sticker(data: str, output_path: str = "sticker_qr.png"):
    """
    Creates a QR code image sized for a .5" x .5" sticker (128x128 pixels ≈ .5" at 300 DPI).
    Returns a PIL.Image object (saved as PNG).
    
    Args:
        data: String to encode (e.g., URL, ID, or short text).
        output_path: Where to save the PNG (default: "sticker_qr.png" in project root).
    
    Example:
        generate_qr_for_sticker("https://example.com/your-sticker-data")
    """
    # Sticker size: 128x128 pixels (matches ~.5" at 300 DPI; clean for print)``
    qr_size = 128

    # Build QR code (minimal, reliable for tiny stickers)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.ERROR_CORRECT_L,
        box_size=1,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    # Create and resize image to exact sticker dimensions
    img = qr.make_image(fill_color="black", back_color="white")
    img.resize((qr_size, qr_size), Image.LANCZOS)

    # Save as PNG (standard for sticker printing)
    img.save(output_path)
    print(f"QR code saved to {output_path} (size: {qr_size}x{qr_size} pixels)")