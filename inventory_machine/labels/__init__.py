"""QR labels, 0.5 in stickers, and printable letter sheets."""
# Imports
import logging

from inventory_machine.labels.generate_page import build_label_sheets, generate_sticker_page
from inventory_machine.labels.qrcode import (
    generate_qr_for_sticker,
    generate_qr_image,
    write_qr_labels,
)

# Globals
logger = logging.getLogger(__name__)

__all__ = [
    "build_label_sheets",
    "generate_qr_for_sticker",
    "generate_qr_image",
    "generate_sticker_page",
    "write_qr_labels",
]
