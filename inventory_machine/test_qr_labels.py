# tests/test_qr_labels.py
"""pytest tests for labels/qrcode.py::generate_qr_for_sticker."""
from PIL import Image

from labels.qrcode import generate_qr_for_sticker

STICKER_SIZE = (128, 128)  # .5" at ~300 DPI


def test_saved_png_has_sticker_size(tmp_path):
    out = tmp_path / "test_qr.png"
    generate_qr_for_sticker("test_qr_342342342valid", out)

    assert out.exists(), f"File not created at {out}"
    with Image.open(out) as img:
        assert img.size == STICKER_SIZE


def test_returned_image_has_sticker_size():
    img = generate_qr_for_sticker("test_qr_asdasdvalid")
    assert img.size == STICKER_SIZE