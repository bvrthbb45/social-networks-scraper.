import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.analysis import image as I
from app.analysis.text import TermSpec, analyze_text


def canvas(bg, fg=None, box=(80, 60, 140, 200), size=(200, 300)):
    im = Image.new("RGB", size, bg)
    if fg:
        im.paste(fg, box)
    return im


def png(im) -> bytes:
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


@pytest.mark.parametrize(
    "img,key",
    [
        (canvas((120, 120, 120), (85, 107, 47)), "uniform-green"),
        (canvas((60, 60, 120), (194, 178, 128)), "uniform-beige"),
    ],
)
def test_uniform_regions_are_flagged_low_severity_and_capped(img, key):
    h = I.uniform_hit(img)
    assert (
        h
        and h.key == key
        and h.kind == "uniform"
        and h.severity == "low"
        and h.score <= 0.6
    )
    assert "אנושית" in h.reason  # always says a human must check


@pytest.mark.parametrize(
    "img",
    [
        canvas((85, 107, 47)),  # whole frame green: scenery / wall
        canvas((120, 120, 120)),
        canvas((60, 100, 200), (30, 60, 150)),
        canvas(
            (120, 120, 120), (85, 107, 47), box=(0, 0, 200, 60)
        ),  # touches 3 edges: a band, not a person
        canvas((120, 120, 120), (85, 107, 47), box=(95, 140, 105, 150)),  # tiny speck
        canvas(
            (120, 120, 120), (85, 107, 47), box=(0, 40, 200, 260)
        ),  # 73% of frame, 2 edges: still scenery
    ],
)
def test_non_uniform_images_not_flagged(img):
    assert I.uniform_hit(img) is None


def test_gps_exif_detected_and_stripped_on_store():
    im = canvas((10, 10, 10), (200, 200, 200))
    exif = Image.Exif()
    exif.get_ifd(0x8825)[1] = "N"
    exif.get_ifd(0x8825)[2] = (32.0, 5.0, 8.0)
    exif.get_ifd(0x8825)[3] = "E"
    exif.get_ifd(0x8825)[4] = (34.0, 46.0, 54.0)
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    raw = buf.getvalue()
    assert I.has_gps(raw)
    assert not I.has_gps(png(im))
    stripped = I.strip_metadata(I.load(raw))
    assert not I.has_gps(stripped)  # what we keep carries no coordinates
    h = I.exif_gps_hit()
    assert h.kind == "location" and h.severity == "high"


@pytest.mark.parametrize(
    "data,code",
    [
        (b"not an image", "unreadable"),
        (b"", "unreadable"),
        (b"\x89PNG\r\n\x1a\n" + b"0" * 50, "unreadable"),
    ],
)
def test_bad_images_rejected(data, code):
    with pytest.raises(I.BadImage) as e:
        I.load(data)
    assert str(e.value) == code


def test_oversize_rejected():
    with pytest.raises(I.BadImage):
        I.load(b"0" * (I.MAX_IMAGE_BYTES + 1))


def test_null_classifier_claims_nothing_and_plugin_is_used():
    im = canvas((1, 1, 1))
    assert I.classifier_hits(I.NullClassifier(), im) == []

    class Fake:
        version = "fake-1"

        def predict(self, img):
            return [
                I.Label("equipment", 0.77, "פריט ציוד צבאי", "high"),
                I.Label("equipment", 0.0, "ignored"),
            ]

    hits = I.classifier_hits(Fake(), im)
    assert len(hits) == 1 and hits[0].kind == "equipment" and hits[0].score == 0.77


@pytest.mark.skipif(not I.ocr_available(), reason="tesseract with Hebrew not installed")
def test_ocr_reads_text_and_feeds_the_text_engines():
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64
    )
    im = Image.new("RGB", (900, 200), "white")
    ImageDraw.Draw(im).text((20, 40), "TOP SECRET", fill="black", font=font)
    text = I.ocr_text(im)
    assert text and "SECRET" in text.upper()
    hits = analyze_text(text, [], "ocr")
    assert any(h.kind == "classified_document" for h in hits)
    heb = Image.new("RGB", (900, 200), "white")
    ImageDraw.Draw(heb).text((20, 40), "בסיס צפוני", fill="black", font=font)
    spec = [TermSpec("t", "בסיס צפוני", (), "site", "high")]
    assert any(
        h.term_id == "t" for h in analyze_text(I.ocr_text(heb) or "", spec, "ocr")
    )
