# inventory_machine/labels/qrcode.py
# Generates a QR code sized for .5" x .5" stickers (128x128 px at ~300 DPI).
# Requires: pip install qrcode[pil]

from pathlib import Path

import qrcode
from PIL import Image

QR_SIZE = 128


def generate_qr_for_sticker(data: str, output_path: str | Path | None = None) -> Image.Image:
    """Build a QR code for `data`, resized to QR_SIZE x QR_SIZE.

    Saves a PNG when `output_path` is given. Always returns the PIL image.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # was the magic number 3
        box_size=1,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((QR_SIZE, QR_SIZE), Image.LANCZOS)  # J1: keep the result

    if output_path:
        img.save(output_path)
    return img