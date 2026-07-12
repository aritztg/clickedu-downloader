"""Clickedu photo album downloader using curl_cffi."""

from __future__ import annotations

import contextlib
import getpass
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import piexif
from bs4 import BeautifulSoup
from curl_cffi import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

logger = logging.getLogger(__name__)

load_dotenv()


@dataclass
class AlbumStats:
    """Per-album download statistics."""

    name: str
    total: int = 0
    downloaded: int = 0
    cached: int = 0
    failed: int = 0
    description: str = ""


@dataclass
class DownloadStats:
    """Aggregate download statistics."""

    albums: list[AlbumStats] = field(default_factory=list)
    total_photos: int = 0
    total_downloaded: int = 0
    total_cached: int = 0
    total_failed: int = 0

    @property
    def failed_albums(self) -> list[AlbumStats]:
        """Albums that had at least one failed download."""
        return [a for a in self.albums if a.failed > 0]


class ClickeduDownloader:  # pylint: disable=too-many-instance-attributes
    """Download all photo albums from a Clickedu school platform."""

    DEFAULT_BASE_URL = "https://dominiquesbcn.clickedu.eu"

    def __init__(
        self,
        base_url: str | None = None,
        download_dir: str = "downloads",
        workers: int = 4,
        dry_run: bool = False,
    ) -> None:
        """
        Args:
            base_url: Clickedu site URL (defaults to Dominiques BCN).
            download_dir: Root directory for downloaded albums.
            workers: Number of parallel download threads.
            dry_run: If True, discover albums but don't download.
        """
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.login_url = f"{self.base_url}/user.php?action=doLogin"
        self.albums_url = f"{self.base_url}/students/albums_fotos.php"

        self.download_dir = Path(download_dir)
        self.workers = workers
        self.dry_run = dry_run
        self.session: requests.Session | None = None
        self.stats = DownloadStats()

    # ── authentication ──────────────────────────────────────────────

    def login(self, username: str | None = None, password: str | None = None) -> None:
        """Authenticate with Clickedu and store the session.

        Credentials are resolved in order: argument → CLICKEDU_USER/CLICKEDU_PASS env vars → prompt.
        """
        username = username or os.getenv("CLICKEDU_USER") or input("Clickedu username: ")
        password = password or os.getenv("CLICKEDU_PASS") or getpass.getpass("Clickedu password: ")

        self.session = requests.Session()
        resp = self.session.post(
            self.login_url,
            data={"username": username, "password": password},
            impersonate="chrome",
        )

        if resp.status_code == 200 and "Iniciar" not in resp.text:
            logger.info("✓ Login successful")
        else:
            logger.error("✗ Login failed — check credentials")
            raise PermissionError("Login failed")

    # ── album discovery ─────────────────────────────────────────────

    def _fetch_album_pages(self) -> list[str]:
        """Return the list of paginated album-listing URLs."""
        pages: list[str] = []
        page = 1

        while True:
            url = f"{self.albums_url}?accio=llistar&pag={page}&lloc=fotos"
            resp = self.session.get(url, impersonate="chrome")  # type: ignore[union-attr]
            soup = BeautifulSoup(resp.text, "html.parser")
            containers = soup.find_all("div", class_="foto_albums_llistat_2")

            if not containers:
                break

            pages.append(url)
            logger.debug("  · page %d: %d albums", page, len(containers))

            if len(containers) < 6:
                break
            page += 1

        return pages

    def _parse_albums_from_page(self, page_url: str) -> list[tuple[str, str, str]]:
        """Parse album links from a listing page.

        Returns:
            List of (url, name, description) tuples.
        """
        resp = self.session.get(page_url, impersonate="chrome")  # type: ignore[union-attr]
        soup = BeautifulSoup(resp.text, "html.parser")
        albums: list[tuple[str, str, str]] = []

        for container in soup.find_all("div", class_="foto_albums_llistat_2"):
            link = container.find("a", href=True)
            name_div = container.find("div", class_="Gran")
            desc_div = container.find("div", class_="Petita")

            if not link or not name_div:
                continue

            album_url = self.base_url + "/students/" + link["href"]
            name = (
                name_div.get_text(strip=True)
                .split("(")[0]
                .strip()
                .replace("\n", " ")
                .replace("\r", "")
                .replace("/", "-")
            )
            description = desc_div.get_text(strip=True) if desc_div else ""

            albums.append((album_url, name, description))

        return albums

    # ── photo extraction ────────────────────────────────────────────

    @staticmethod
    def _extract_photos_from_album(album_page: str) -> list[str]:
        """Return list of full-size photo URLs from an album page."""
        soup = BeautifulSoup(album_page, "html.parser")
        gallery = soup.find("ul", class_="image-gallery")
        if not gallery:
            return []

        photos: list[str] = []
        for link in gallery.find_all("a", href=True):
            href = link["href"]
            if href.startswith("http") and "/grans/" in href:
                photos.append(href)

        return photos

    # ── EXIF helpers ────────────────────────────────────────────────

    @staticmethod
    def _has_exif_date(image_bytes: bytes) -> bool:
        """Check if image bytes already have a DateTimeOriginal EXIF tag."""
        try:
            exif = piexif.load(image_bytes)
            return piexif.ExifIFD.DateTimeOriginal in exif.get("Exif", {})
        except (ValueError, piexif.InvalidImageDataError, OSError):
            return False

    @staticmethod
    def _extract_datetime_from_filename(filename: str) -> datetime | None:
        """Try to extract a datetime from common filename patterns.

        Patterns supported:
            - UNIX millisecond timestamps: 1781603067258.jpg
            - YYYYMMDD_HHMMSS: 20241005_143000
            - ISO-ish: 2024-10-05 14:30, 20241005-1430
        """
        basename = Path(filename).stem

        # UNIX millisecond timestamp (13 digits)
        if re.match(r"^\d{13}$", basename):
            try:
                return datetime.fromtimestamp(int(basename) / 1000)
            except (ValueError, OSError):
                pass

        # UNIX second timestamp (10 digits)
        if re.match(r"^\d{10}$", basename):
            try:
                return datetime.fromtimestamp(int(basename))
            except (ValueError, OSError):
                pass

        patterns = [
            r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})",  # 20241005_143000
            r"(\d{4})-(\d{2})-(\d{2})[T _](\d{2})[.:](\d{2})",  # 2024-10-05 14:30
            r"(\d{4})(\d{2})(\d{2})[-_](\d{2})(\d{2})",  # 20241005-1430
        ]

        for pattern in patterns:
            match = re.search(pattern, basename)
            if match:
                groups = match.groups()
                try:
                    if len(groups) == 6:
                        return datetime(
                            int(groups[0]), int(groups[1]), int(groups[2]),
                            int(groups[3]), int(groups[4]), int(groups[5]),
                        )
                    if len(groups) == 5:
                        return datetime(
                            int(groups[0]), int(groups[1]), int(groups[2]),
                            int(groups[3]), int(groups[4]), 0,
                        )
                except ValueError:
                    continue

        return None

    @staticmethod
    def _set_exif_datetime(image_path: Path, dt: datetime) -> None:
        """Write the EXIF DateTimeOriginal tag to a JPEG file."""
        dt_str = dt.strftime("%Y:%m:%d %H:%M:%S")

        try:
            exif_dict = piexif.load(str(image_path))
        except (ValueError, piexif.InvalidImageDataError, OSError):
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

        # Already has date? skip
        if piexif.ExifIFD.DateTimeOriginal in exif_dict.get("Exif", {}):
            return

        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt_str
        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = dt_str

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, str(image_path))

    # ── download ────────────────────────────────────────────────────

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _fetch_photo(self, photo_url: str) -> requests.Response:
        """Fetch a single photo with retry on failure."""
        resp = self.session.get(photo_url, timeout=30, impersonate="chrome")  # type: ignore[union-attr]
        resp.raise_for_status()
        return resp

    def download_photo(self, photo_url: str, dest_path: Path) -> bool:
        """Download a single photo and set its EXIF date if missing.

        Idempotent: skips download if the file already exists.
        Retries up to 3 times with exponential backoff.
        Verifies Content-Length matches downloaded bytes.

        Returns:
            True on success (or already present), False on failure.
        """
        if dest_path.exists() or dest_path.with_suffix(dest_path.suffix.upper()).exists():
            return True

        try:
            resp = self._fetch_photo(photo_url)
        except requests.RequestsError:
            logger.error("✗ Download failed after retries: %s", photo_url)
            return False

        content = resp.content
        expected_length = resp.headers.get("Content-Length")
        if expected_length and len(content) != int(expected_length):
            logger.error(
                "✗ Size mismatch for %s: expected %s, got %d",
                photo_url, expected_length, len(content),
            )
            return False

        dest_path.write_bytes(content)

        # Preserve server's Last-Modified as local file mtime
        last_modified = resp.headers.get("Last-Modified")
        if last_modified:
            try:
                server_dt = parsedate_to_datetime(last_modified)
                ts = server_dt.timestamp()
                os.utime(dest_path, (ts, ts))
            except (ValueError, OSError):
                pass

        # Only inject EXIF date if the photo doesn't already have one
        if not self._has_exif_date(content):
            dt = self._extract_datetime_from_filename(photo_url)
            if dt:
                with contextlib.suppress(Exception):
                    self._set_exif_datetime(dest_path, dt)

        return True

    # ── album helpers ───────────────────────────────────────────────

    @staticmethod
    def _count_existing_photos(album_dir: Path, total: int) -> int:
        """Count how many photos already exist on disk (any extension case)."""
        extensions_lower = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
        extensions_upper = [ext.upper() for ext in extensions_lower]
        return sum(
            1 for i in range(1, total + 1)
            if (album_dir / f"{i:04d}.jpg").exists()
            or any((album_dir / f"{i:04d}{ext}").exists() for ext in extensions_lower)
            or any((album_dir / f"{i:04d}{ext}").exists() for ext in extensions_upper)
        )

    @staticmethod
    def _save_album_description(album_dir: Path, soup: BeautifulSoup, fallback: str = "") -> str:
        """Extract and save album description. Returns the description text."""
        desc_div = soup.find("div", class_="xxxPerSobre")
        description = desc_div.get_text(strip=True) if desc_div else fallback
        if description and description != "No disposeu de permisos.":
            (album_dir / "description.txt").write_text(description, encoding="utf-8")
        return description

    # ── album download ──────────────────────────────────────────────

    def _download_photos_parallel(self, photos: list[str], album_dir: Path, album_name: str) -> tuple[int, int]:
        """Download photos in parallel and return (downloaded, failed) counts."""
        downloaded = 0
        failed = 0
        futures: dict = {}
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            for i, photo_url in enumerate(photos, 1):
                ext = Path(photo_url).suffix.lower() or ".jpg"
                dest = album_dir / f"{i:04d}{ext}"
                if dest.exists() or dest.with_suffix(dest.suffix.upper()).exists():
                    continue
                futures[executor.submit(self.download_photo, photo_url, dest)] = dest

            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                desc=f"  {album_name}",
                unit="photo",
                leave=False,
            ):
                if future.result():
                    downloaded += 1
                else:
                    failed += 1
        return downloaded, failed

    def download_album(self, album_url: str, album_name: str, description: str = "") -> AlbumStats:
        """Download all photos from a single album. Returns stats."""
        album_dir = self.download_dir / album_name
        album_dir.mkdir(parents=True, exist_ok=True)

        # Fetch album page
        resp = self.session.get(album_url, impersonate="chrome")  # type: ignore[union-attr]
        soup = BeautifulSoup(resp.text, "html.parser")
        album_description = self._save_album_description(album_dir, soup, description)

        photos = self._extract_photos_from_album(resp.text)

        stats = AlbumStats(name=album_name, total=len(photos), description=album_description)

        if not photos:
            logger.warning("⚠ No photos found in '%s'", album_name)
            return stats

        existing = self._count_existing_photos(album_dir, len(photos))
        stats.cached = existing
        new_photos = len(photos) - existing

        if new_photos == 0:
            logger.info("  📁 %s — %d photos (all cached)", album_name, len(photos))
            return stats

        if self.dry_run:
            logger.info("  📁 %s — %d new / %d total (dry-run)", album_name, new_photos, len(photos))
            return stats

        logger.info("  📁 %s — %d new / %d total", album_name, new_photos, len(photos))

        downloaded, failed = self._download_photos_parallel(photos, album_dir, album_name)
        stats.downloaded = downloaded
        stats.failed = failed

        return stats

    # ── manifest ────────────────────────────────────────────────────

    def _generate_manifest(self, albums: list[AlbumStats]) -> None:
        """Write albums.json manifest with metadata for all albums."""
        manifest = []
        for a in albums:
            album_dir = self.download_dir / a.name
            date_range = self._album_date_range(album_dir)
            manifest.append({
                "name": a.name,
                "description": a.description,
                "photos": a.total,
                "downloaded": a.downloaded,
                "cached": a.cached,
                "failed": a.failed,
                "earliest_date": date_range[0].isoformat() if date_range[0] else None,
                "latest_date": date_range[1].isoformat() if date_range[1] else None,
            })

        path = self.download_dir / "albums.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("📋 Manifest saved to %s", path)

    @staticmethod
    def _album_date_range(album_dir: Path) -> tuple[datetime | None, datetime | None]:
        """Find the earliest and latest EXIF dates in an album folder."""
        earliest: datetime | None = None
        latest: datetime | None = None
        for photo in sorted(album_dir.glob("*")):
            if photo.suffix.lower() not in (".jpg", ".jpeg"):
                continue
            try:
                exif = piexif.load(str(photo))
                dt_str = exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
                if dt_str:
                    dt = datetime.strptime(dt_str.decode(), "%Y:%m:%d %H:%M:%S")
                    if earliest is None or dt < earliest:
                        earliest = dt
                    if latest is None or dt > latest:
                        latest = dt
            except (ValueError, piexif.InvalidImageDataError, OSError):
                continue
        return earliest, latest

    # ── summary ─────────────────────────────────────────────────────

    def _print_summary(self) -> None:
        """Print download summary with error details."""
        s = self.stats
        logger.info("")
        logger.info("=" * 50)
        logger.info("📊 Download Summary")
        logger.info("=" * 50)
        logger.info("  Albums:       %d", len(s.albums))
        logger.info("  Total photos: %d", s.total_photos)
        logger.info("  Downloaded:   %d", s.total_downloaded)
        logger.info("  Cached:       %d", s.total_cached)
        logger.info("  Failed:       %d", s.total_failed)

        if s.failed_albums:
            logger.warning("")
            logger.warning("⚠ Albums with failures:")
            for a in s.failed_albums:
                logger.warning("  - %s: %d/%d failed", a.name, a.failed, a.total)

        logger.info("=" * 50)

    # ── top-level runner ────────────────────────────────────────────

    def run(
        self,
        username: str | None = None,
        password: str | None = None,
        album_filter: str | None = None,
    ) -> None:
        """Authenticate and download all albums (or a single one if filtered)."""
        self.login(username, password)

        logger.info("Scanning album pages…")
        pages = self._fetch_album_pages()

        all_albums: list[tuple[str, str, str]] = []
        for page_url in pages:
            all_albums.extend(self._parse_albums_from_page(page_url))

        if album_filter:
            all_albums = [
                (url, name, desc) for url, name, desc in all_albums
                if album_filter.lower() in name.lower()
            ]
            if not all_albums:
                logger.warning("No albums matching '%s'", album_filter)
                return

        logger.info("Found %d album(s)", len(all_albums))

        for album_url, name, desc in tqdm(all_albums, desc="Downloading albums", unit="album"):
            album_stats = self.download_album(album_url, name, desc)
            self.stats.albums.append(album_stats)
            self.stats.total_photos += album_stats.total
            self.stats.total_downloaded += album_stats.downloaded
            self.stats.total_cached += album_stats.cached
            self.stats.total_failed += album_stats.failed

        self._print_summary()
        self._generate_manifest(self.stats.albums)
        logger.info("✓ Done! Photos saved to %s", self.download_dir.resolve())
