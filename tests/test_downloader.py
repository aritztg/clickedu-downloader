"""Unit tests for ClickeduDownloader."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import piexif
import pytest

from clickedu_downloader.downloader import ClickeduDownloader


# ── JPEG fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def real_jpeg() -> bytes:
    """A valid JPEG that piexif can round-trip."""
    path = Path("downloads/BIRRETS I5/0001.jpg")
    if path.exists():
        return path.read_bytes()
    for p in Path("downloads").rglob("*.jpg"):
        return p.read_bytes()
    pytest.skip("No real JPEG available — run the downloader first")


def _piexif_insert(exif_bytes: bytes, image: bytes) -> bytes:
    """Insert EXIF into JPEG bytes, return new bytes."""
    buf = io.BytesIO()
    piexif.insert(exif_bytes, image, buf)
    return buf.getvalue()


def _piexif_remove(image: bytes) -> bytes:
    """Remove EXIF from JPEG bytes, return new bytes."""
    buf = io.BytesIO()
    piexif.remove(image, buf)
    return buf.getvalue()


@pytest.fixture
def stripped_jpeg(real_jpeg: bytes) -> bytes:
    """A JPEG with all EXIF data removed."""
    return _piexif_remove(real_jpeg)


@pytest.fixture
def jpeg_with_exif(real_jpeg: bytes) -> bytes:
    """A JPEG with DateTimeOriginal EXIF tag set to a known date."""
    exif_dict = piexif.load(real_jpeg)
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2024:06:15 12:00:00"
    exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = b"2024:06:15 12:00:00"
    return _piexif_insert(piexif.dump(exif_dict), real_jpeg)


# ── datetime extraction ─────────────────────────────────────────────

@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("1781603067258.jpg", datetime(2026, 6, 16, 9, 44, 27, 258000)),
        ("1781603067258", datetime(2026, 6, 16, 9, 44, 27, 258000)),
        ("1717000000.jpg", datetime(2024, 5, 29, 16, 26, 40)),
        ("20241005_143000.jpg", datetime(2024, 10, 5, 14, 30)),
        ("20260619_100923.jpg", datetime(2026, 6, 19, 10, 9, 23)),
        ("IMG_20260619_101234.jpg", datetime(2026, 6, 19, 10, 12, 34)),
        ("IMG_20260619_101758.JPG", datetime(2026, 6, 19, 10, 17, 58)),
        ("2024-10-05 14:30.jpg", datetime(2024, 10, 5, 14, 30)),
        ("2024-10-05T14:30:00.jpg", datetime(2024, 10, 5, 14, 30)),
        ("20241005-1430.jpg", datetime(2024, 10, 5, 14, 30)),
        ("/some/path/1781603067258.jpg", datetime(2026, 6, 16, 9, 44, 27, 258000)),
        ("IMG_1606.JPG", None),
        ("photo.jpg", None),
        ("", None),
    ],
)
def test_extract_datetime_from_filename(filename: str, expected: datetime | None) -> None:
    result = ClickeduDownloader._extract_datetime_from_filename(filename)
    assert result == expected


# ── EXIF helpers ─────────────────────────────────────────────────────

def test_has_exif_date_with_date(jpeg_with_exif: bytes) -> None:
    assert ClickeduDownloader._has_exif_date(jpeg_with_exif) is True


def test_has_exif_date_without_date(stripped_jpeg: bytes) -> None:
    assert ClickeduDownloader._has_exif_date(stripped_jpeg) is False


def test_has_exif_date_invalid_bytes() -> None:
    assert ClickeduDownloader._has_exif_date(b"not a jpeg") is False


def test_set_exif_datetime_injects_date(tmp_path: Path, stripped_jpeg: bytes) -> None:
    path = tmp_path / "test.jpg"
    path.write_bytes(stripped_jpeg)

    dt = datetime(2025, 3, 15, 10, 30, 0)
    ClickeduDownloader._set_exif_datetime(path, dt)

    exif = piexif.load(str(path))
    assert exif["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2025:03:15 10:30:00"
    assert exif["Exif"][piexif.ExifIFD.DateTimeDigitized] == b"2025:03:15 10:30:00"


def test_set_exif_datetime_skips_if_present(tmp_path: Path, jpeg_with_exif: bytes) -> None:
    path = tmp_path / "with_exif.jpg"
    path.write_bytes(jpeg_with_exif)

    new_dt = datetime(2025, 12, 25, 0, 0, 0)
    ClickeduDownloader._set_exif_datetime(path, new_dt)

    exif = piexif.load(str(path))
    assert exif["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2024:06:15 12:00:00"


# ── photo extraction ────────────────────────────────────────────────

ALBUM_HTML = """<html><body>
<ul class="image-gallery">
  <li><a href="https://example.com/private/fotos/1/grans/photo1.jpg">...</a></li>
  <li><a href="https://example.com/private/fotos/1/grans/photo2.JPG">...</a></li>
  <li><a href="https://example.com/private/fotos/1/petites/thumb.jpg">...</a></li>
  <li><a href="photo3.jpg">...</a></li>
</ul>
</body></html>"""


def test_extract_photos_from_album() -> None:
    photos = ClickeduDownloader._extract_photos_from_album(ALBUM_HTML)
    assert len(photos) == 2
    assert photos[0] == "https://example.com/private/fotos/1/grans/photo1.jpg"
    assert photos[1] == "https://example.com/private/fotos/1/grans/photo2.JPG"


def test_extract_photos_empty_gallery() -> None:
    html = "<html><body><ul class='image-gallery'></ul></body></html>"
    assert ClickeduDownloader._extract_photos_from_album(html) == []


def test_extract_photos_no_gallery() -> None:
    html = "<html><body><p>No photos here</p></body></html>"
    assert ClickeduDownloader._extract_photos_from_album(html) == []


# ── constructor ─────────────────────────────────────────────────────

def test_default_base_url() -> None:
    d = ClickeduDownloader()
    assert d.BASE_URL == "https://dominiquesbcn.clickedu.eu"


def test_custom_base_url() -> None:
    d = ClickeduDownloader(base_url="https://myschool.clickedu.eu")
    assert d.BASE_URL == "https://myschool.clickedu.eu"
    assert d.LOGIN_URL == "https://myschool.clickedu.eu/user.php?action=doLogin"


def test_default_download_dir() -> None:
    d = ClickeduDownloader()
    assert d.download_dir == Path("downloads")


def test_custom_download_dir() -> None:
    d = ClickeduDownloader(download_dir="/tmp/photos")
    assert d.download_dir == Path("/tmp/photos")


# ── idempotency ─────────────────────────────────────────────────────

def test_download_photo_skips_existing_file(tmp_path: Path, stripped_jpeg: bytes) -> None:
    d = ClickeduDownloader()
    d.session = None

    path = tmp_path / "photo.jpg"
    path.write_bytes(stripped_jpeg)

    assert d.download_photo("http://example.com/photo.jpg", path) is True


def test_download_photo_skips_case_variant(tmp_path: Path, stripped_jpeg: bytes) -> None:
    d = ClickeduDownloader()
    d.session = None

    path_upper = tmp_path / "photo.JPG"
    path_upper.write_bytes(stripped_jpeg)

    path_lower = tmp_path / "photo.jpg"
    assert d.download_photo("http://example.com/photo.jpg", path_lower) is True
