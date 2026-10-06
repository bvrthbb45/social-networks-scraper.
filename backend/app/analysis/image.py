"""Image engines (local only).

What is real here, and what is not
* ``uniform_hit``  - a COLOUR heuristic (olive-green / beige regions of person-like size). It is a
  weak signal: scores are capped low and every hit goes to a human. Loop 6 learns from reviewer
  decisions to calibrate it.
* ``exif_gps_hit`` - GPS coordinates embedded in the file: a precise, reliable location leak.
* ``ocr_text``     - Tesseract (Hebrew + English) if installed; text found is run through the text
  engines (classification markers, coordinates, watch-list).
* ``Classifier``   - the plug-in point for a trained model (equipment, aircraft, classified-looking
  items, screens). NO model is shipped: weights are organisation data and are loaded from
  ``MODEL_DIR`` when present. Until then these kinds are simply not reported.
"""

import io
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import ExifTags, Image, ImageOps

from .text import Hit

Image.MAX_IMAGE_PIXELS = (
    40_000_000  # decompression-bomb guard (Pillow raises above 2x this)
)
MAX_IMAGE_BYTES = 8 * 1024 * 1024

# HSV with PIL scaling (all channels 0-255). Hue degrees * 255/360.
_OLIVE = dict(h=(33, 66), s=(45, 190), v=(35, 175))  # ~47-93 deg: olive / army green
_BEIGE = dict(h=(17, 33), s=(28, 120), v=(120, 235))  # ~24-47 deg: sand / khaki / beige


class BadImage(Exception):
    pass


def load(data: bytes) -> Image.Image:
    if len(data) > MAX_IMAGE_BYTES:
        raise BadImage("too_large")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img.load()
    except Exception as e:  # PIL raises many types
        raise BadImage("unreadable") from e
    if img.format not in (None, "JPEG", "PNG", "WEBP", "GIF") and img.format != "MPO":
        raise BadImage("format_not_allowed")
    return img.convert("RGB")


def strip_metadata(img: Image.Image) -> bytes:
    """Re-encode without EXIF/ICC/comments. Stored media never keeps embedded metadata."""
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


# --- EXIF GPS ---------------------------------------------------------------------------- #


def has_gps(data: bytes) -> bool:
    try:
        exif = Image.open(io.BytesIO(data)).getexif()
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        return bool(gps) and (1 in gps or 2 in gps or 3 in gps or 4 in gps)
    except Exception:
        return False


def exif_gps_hit() -> Hit:
    return Hit(
        "location",
        "high",
        0.85,
        "קובץ התמונה מכיל נתוני מיקום GPS מוטבעים",
        "exif",
        "",
        None,
        "exif-gps",
    )


# --- colour heuristic --------------------------------------------------------------------- #


def _mask(hsv: np.ndarray, r: dict) -> np.ndarray:
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return (
        (h >= r["h"][0])
        & (h <= r["h"][1])
        & (s >= r["s"][0])
        & (s <= r["s"][1])
        & (v >= r["v"][0])
        & (v <= r["v"][1])
    )


def _largest_blob(cells: np.ndarray) -> tuple[int, set[str]]:
    """Largest 4-connected component of True cells; also which image edges it touches."""
    rows, cols = cells.shape
    seen = np.zeros_like(cells, dtype=bool)
    best, best_edges = 0, set()
    for r0 in range(rows):
        for c0 in range(cols):
            if not cells[r0, c0] or seen[r0, c0]:
                continue
            stack, n, edges = [(r0, c0)], 0, set()
            seen[r0, c0] = True
            while stack:
                r, c = stack.pop()
                n += 1
                if r == 0:
                    edges.add("top")
                if r == rows - 1:
                    edges.add("bottom")
                if c == 0:
                    edges.add("left")
                if c == cols - 1:
                    edges.add("right")
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    rr, cc = r + dr, c + dc
                    if (
                        0 <= rr < rows
                        and 0 <= cc < cols
                        and cells[rr, cc]
                        and not seen[rr, cc]
                    ):
                        seen[rr, cc] = True
                        stack.append((rr, cc))
            if n > best:
                best, best_edges = n, edges
    return best, best_edges


def uniform_hit(img: Image.Image) -> Hit | None:
    """Look for ONE coherent olive/beige region of person-like size that does not fill the frame
    (full-frame green/beige is scenery or a wall, not a garment)."""
    small = img.resize((128, 128))
    hsv = np.asarray(small.convert("HSV"), dtype=np.uint8)
    best: tuple[float, str] | None = None
    for name, rng in (("green", _OLIVE), ("beige", _BEIGE)):
        mask = _mask(hsv, rng)
        cells = (
            mask.reshape(16, 8, 16, 8).mean(axis=(1, 3)) >= 0.6
        )  # 16x16 grid of 8px cells
        n, edges = _largest_blob(cells)
        share = n / 256
        if n < 12 or share > 0.55 or len(edges) >= 3:
            continue
        score = min(0.6, round(0.3 + 1.2 * share, 3))
        if best is None or score > best[0]:
            best = (score, name)
    if best is None:
        return None
    colour = "ירוק-זית" if best[1] == "green" else "בז'/חאקי"
    return Hit(
        "uniform",
        "low",
        best[0],
        f"זוהה אזור גדול וקוהרנטי בגוון {colour} האופייני למדים (אינדיקציה חלשה – נדרשת בדיקה אנושית)",
        "image",
        "",
        None,
        f"uniform-{best[1]}",
    )


# --- OCR ---------------------------------------------------------------------------------- #


def ocr_available() -> bool:
    try:
        import pytesseract

        return "heb" in pytesseract.get_languages(config="")
    except Exception:
        return False


def ocr_text(img: Image.Image) -> str | None:
    """Text found in the image, or None if OCR is unavailable (the pipeline degrades gracefully)."""
    try:
        import pytesseract
    except ImportError:
        return None
    if not ocr_available():
        return None
    work = img.copy()
    work.thumbnail((2000, 2000))
    try:
        return pytesseract.image_to_string(
            ImageOps.autocontrast(work.convert("L")), lang="heb+eng", timeout=20
        )
    except Exception:
        return None


# --- learned classifier plug-in ------------------------------------------------------------ #


@dataclass(frozen=True)
class Label:
    kind: str  # equipment | classified_document | screen_photo | uniform
    score: float
    reason: str
    severity: str = "medium"


class Classifier(Protocol):
    version: str

    def predict(self, img: Image.Image) -> list[Label]: ...


class NullClassifier:
    """Default: no trained model available, so nothing is claimed."""

    version = "none"

    def predict(self, img: Image.Image) -> list[Label]:
        return []


def classifier_hits(clf: Classifier, img: Image.Image) -> list[Hit]:
    return [
        Hit(
            l.kind,
            l.severity,
            round(l.score, 3),
            l.reason,
            "image",
            "",
            None,
            f"clf-{l.kind}",
        )
        for l in clf.predict(img)
        if 0 < l.score <= 1
    ]
