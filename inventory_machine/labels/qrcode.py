"""
Author: Jesse
Date:   2026

Description:
    Builds QR images and writes one label per occupied location
    or unlocated item.
"""
# Imports
import logging
from configparser import ConfigParser, Error as ConfigError
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_M

from inventory_machine.labels.generate_page import build_label_sheets

# Globals
logger = logging.getLogger(__name__)

_DPI = 300
_MM_PER_INCH = 25.4
_TEXT_LIMIT = 60
QR_SIZE = 128


# Functions
def _mm_to_px(mm: float) -> int:
    """
    Input: mm -- length in millimetres.
    Output: pixel count at 300 DPI.
    Details:
        25.4 mm is one inch.
    """
    return round(mm / _MM_PER_INCH * _DPI)


def generate_qr_image(data: str, size_px: int) -> Image.Image:
    """
    Input: data -- string stored in the QR code. size_px -- side in pixels.
    Output: an RGB image of size_px by size_px.
    Details:
        Medium error correction. Nearest-neighbor resize keeps modules sharp.
    """
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        return img.resize((size_px, size_px), Image.NEAREST)
    except Exception:
        logger.exception("Failed to generate QR image")
        raise


def generate_qr_for_sticker(data: str, output_path: str | Path | None = None) -> Image.Image:
    """
    Input: data -- string stored in the QR code. output_path -- optional PNG path.
    Output: a QR_SIZE by QR_SIZE RGB image for a 0.5 in sticker.
    Details:
        Saves a PNG when output_path is given.
    """
    img = generate_qr_image(data, QR_SIZE)
    if output_path:
        try:
            img.save(output_path)
        except OSError:
            logger.exception("Could not save sticker QR %s", output_path)
            raise
    return img


def _location_path(db, location_id: int) -> str:
    """
    Input: db -- Database. location_id -- start location.
    Output: names from the root to this location, joined with " > ".
    Details:
        Stops if a parent chain repeats, so a cycle cannot loop forever.
    """
    names = []
    seen = set()
    current = location_id
    while current is not None:
        if current in seen:
            logger.warning("Location parent cycle at id %s", current)
            break
        seen.add(current)
        row = db.fetch_one(
            "SELECT name, parent_location_id FROM locations WHERE id = ?",
            (current,),
        )
        if row is None:
            logger.warning("Location id %s is missing", current)
            break
        names.append(row[0])
        current = row[1]
    names.reverse()
    return " > ".join(names)


def _truncate_text(text: str, limit: int = _TEXT_LIMIT) -> str:
    """
    Input: text -- source string. limit -- maximum length, about 60.
    Output: text, or a shortened form with an ellipsis.
    """
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """
    Input: text, font, max_width in pixels, and a Draw object.
    Output: wrapped lines that fit max_width.
    """
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _line_height(font) -> int:
    """
    Input: font -- a PIL font.
    Output: line step in pixels, including a small gap.
    """
    bbox = font.getbbox("Ag")
    return (bbox[3] - bbox[1]) + 4


def _render_label(url: str, text: str, width_px: int, height_px: int) -> Image.Image:
    """
    Input: url -- QR payload. text -- caption. width_px, height_px -- label size.
    Output: an RGB label with the QR on the left and wrapped text on the right.
    """
    canvas = Image.new("RGB", (width_px, height_px), "white")
    margin = max(4, height_px // 24)
    qr_side = max(1, height_px - 2 * margin)
    canvas.paste(generate_qr_image(url, qr_side), (margin, margin))
    text_left = margin + qr_side + margin
    text_width = width_px - text_left - margin
    if text_width < 8:
        return canvas
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=max(10, height_px // 14))
    y = margin
    max_y = height_px - margin
    step = _line_height(font)
    for line in _wrap_text(text, font, text_width, draw):
        if y + step > max_y:
            break
        draw.text((text_left, y), line, fill="black", font=font)
        y += step
    return canvas


def _upsert_qr_label(
    db,
    location_id: int | None,
    item_id: str | None,
    label_text: str,
    qr_url: str,
    qr_image_path: str,
) -> None:
    """
    Input: db and the qr_labels fields for one location or one item.
    Output: None.
    Details:
        Updates the existing row for that location_id or item_id.
        Inserts a row when none exists. The table check needs exactly
        one of location_id or item_id.
    """
    if location_id is not None:
        row = db.fetch_one(
            "SELECT id FROM qr_labels WHERE location_id = ?",
            (location_id,),
        )
    else:
        row = db.fetch_one(
            "SELECT id FROM qr_labels WHERE item_id = ?",
            (item_id,),
        )
    if row:
        db.execute(
            "UPDATE qr_labels SET label_text = ?, qr_url = ?, qr_image_path = ? "
            "WHERE id = ?",
            (label_text, qr_url, qr_image_path, row[0]),
        )
        return
    db.execute(
        "INSERT INTO qr_labels "
        "(location_id, item_id, label_text, qr_url, qr_image_path) "
        "VALUES (?, ?, ?, ?, ?)",
        (location_id, item_id, label_text, qr_url, qr_image_path),
    )


def _save_label(
    db,
    output_dir: Path,
    filename: str,
    location_id: int | None,
    item_id: str | None,
    text: str,
    url: str,
    width_px: int,
    height_px: int,
) -> str:
    """
    Input: db, output directory, file name, row keys, caption, URL, size.
    Output: filesystem path of the saved PNG.
    """
    path = output_dir / filename
    try:
        _render_label(url, text, width_px, height_px).save(path)
    except OSError:
        logger.exception("Could not save label %s", path)
        raise
    _upsert_qr_label(db, location_id, item_id, text, url, str(path))
    return str(path)


def write_qr_labels(db, cfg: ConfigParser) -> int:
    """
    Input: db -- Database. cfg -- config with [paths] and [labels].
    Output: number of label images written.
    Details:
        One label per location that directly holds an item, plus one
        label per item with a null location_id. Sheets are written to
        the same qr_output_dir after the labels.
    """
    try:
        output_dir = Path(cfg.get("paths", "qr_output_dir"))
        base_url = cfg.get("labels", "qr_base_url").rstrip("/")
        width_mm = cfg.getfloat("labels", "label_width_mm")
        height_mm = cfg.getfloat("labels", "label_height_mm")
    except (ConfigError, ValueError):
        logger.exception("Label config is missing or invalid")
        raise
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Could not create QR output directory %s", output_dir)
        raise
    width_px = _mm_to_px(width_mm)
    height_px = _mm_to_px(height_mm)
    location_ids = db.fetch_all(
        "SELECT DISTINCT location_id FROM items "
        "WHERE location_id IS NOT NULL ORDER BY location_id"
    )
    unlocated = db.fetch_all(
        "SELECT id, description FROM items "
        "WHERE location_id IS NULL ORDER BY id"
    )
    label_paths = []
    for (location_id,) in location_ids:
        text = _location_path(db, location_id)
        url = f"{base_url}/location/{location_id}"
        label_paths.append(
            _save_label(
                db,
                output_dir,
                f"location_{location_id}.png",
                location_id,
                None,
                text,
                url,
                width_px,
                height_px,
            )
        )
    for item_id, description in unlocated:
        text = _truncate_text(description)
        url = f"{base_url}/item/{item_id}"
        label_paths.append(
            _save_label(
                db,
                output_dir,
                f"item_{item_id}.png",
                None,
                item_id,
                text,
                url,
                width_px,
                height_px,
            )
        )
    build_label_sheets(label_paths, str(output_dir))
    logger.info("Wrote %s QR labels to %s", len(label_paths), output_dir)
    return len(label_paths)
