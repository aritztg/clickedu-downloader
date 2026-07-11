"""Clickedu photo album downloader using curl_cffi."""

from __future__ import annotations

import contextlib
import getpass
import os
import re
from datetime import datetime
from pathlib import Path

import piexif
from bs4 import BeautifulSoup
from curl_cffi import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

load_dotenv()


class ClickeduDownloader:
    """Download all photo albums from a Clickedu school platform."""

    BASE_URL = "https://dominiquesbcn.clickedu.eu"
    LOGIN_URL = f"{BASE_URL}/user.php?action=doLogin"
    ALBUMS_URL = f"{BASE_URL}/students/albums_fotos.php"

    def __init__(self, base_url: str | None = None, download_dir: str = "downloads"):
        """
        Args:
            base_url: Clickedu site URL (defaults to Dominiques BCN).
            download_dir: Root directory for downloaded albums.
        """
        if base_url:
            self.BASE_URL = base_url
            self.LOGIN_URL = f"{base_url}/user.php?action=doLogin"
            self.ALBUMS_URL = f"{base_url}/students/albums_fotos.php"

        self.download_dir = Path(download_dir)
        self.session: requests.Session | None = None

    # ── authentication ──────────────────────────────────────────────

    def login(self, username: str | None = None, password: str | None = None) -> None:
        """Authenticate with Clickedu and store the session.

        Credentials are resolved in order: argument → CLICKEDU_USER/CLICKEDU_PASS env vars → prompt.
        """
        username = username or os.getenv("CLICKEDU_USER") or input("Clickedu username: ")
        password = password or os.getenv("CLICKEDU_PASS") or getpass.getpass("Clickedu password: ")

        self.session = requests.Session()
        resp = self.session.post(
            self.LOGIN_URL,
            data={"username": username, "password": password},
            impersonate="chrome",
        )

        if resp.status_code == 200 and "Iniciar" not in resp.text:
            console.print("[green]✓ Login successful[/]")
        else:
            console.print("[red]✗ Login failed — check credentials[/]")
            raise PermissionError("Login failed")

    # ── album discovery ─────────────────────────────────────────────

    def _fetch_album_pages(self) -> list[str]:
        """Return the list of paginated album-listing URLs."""
        pages: list[str] = []
        page = 1

        while True:
            url = f"{self.ALBUMS_URL}?accio=llistar&pag={page}&lloc=fotos"
            resp = self.session.get(url, impersonate="chrome")  # type: ignore[union-attr]
            soup = BeautifulSoup(resp.text, "html.parser")
            containers = soup.find_all("div", class_="foto_albums_llistat_2")

            if not containers:
                break

            pages.append(url)
            console.print(f"  · page {page}: {len(containers)} albums")

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

            album_url = self.BASE_URL + "/students/" + link["href"]
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
        except Exception:
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
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

        # Already has date? skip
        if piexif.ExifIFD.DateTimeOriginal in exif_dict.get("Exif", {}):
            return

        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt_str
        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = dt_str

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, str(image_path))

    # ── download ────────────────────────────────────────────────────

    def download_photo(self, photo_url: str, dest_path: Path) -> bool:
        """Download a single photo and set its EXIF date if missing.

        Idempotent: skips download if the file already exists.
        Skips EXIF injection if DateTimeOriginal is already present.

        Returns:
            True on success (or already present), False on download failure.
        """
        # Idempotency: skip if already downloaded
        if dest_path.exists():
            return True

        try:
            resp = self.session.get(photo_url, timeout=30, impersonate="chrome")  # type: ignore[union-attr]
            resp.raise_for_status()
        except Exception as exc:
            console.print(f"    [red]✗ download failed: {photo_url} — {exc}[/]")
            return False

        content = resp.content
        dest_path.write_bytes(content)

        # Only inject EXIF date if the photo doesn't already have one
        if not self._has_exif_date(content):
            dt = self._extract_datetime_from_filename(photo_url)
            if dt:
                with contextlib.suppress(Exception):
                    self._set_exif_datetime(dest_path, dt)

        return True

    def download_album(self, album_url: str, album_name: str, description: str = "") -> None:
        """Download all photos from a single album.

        Idempotent: skips already-downloaded photos.

        Args:
            album_url: Full URL of the album page.
            album_name: Human-readable name (used as folder name).
            description: Album description to save as album_info.txt.
        """
        album_dir = self.download_dir / album_name
        album_dir.mkdir(parents=True, exist_ok=True)

        # Save description (always overwrite with latest)
        info_path = album_dir / "album_info.txt"
        if description and not info_path.exists():
            info_path.write_text(description, encoding="utf-8")

        # Fetch album page
        resp = self.session.get(album_url, impersonate="chrome")  # type: ignore[union-attr]
        photos = self._extract_photos_from_album(resp.text)

        if not photos:
            console.print(f"  [yellow]⚠ no photos found in '{album_name}'[/]")
            return

        # Count already-downloaded
        existing = sum(1 for i in range(1, len(photos) + 1)
                       if (album_dir / f"{i:04d}.jpg").exists()
                       or any((album_dir / f"{i:04d}{ext}").exists()
                              for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]))

        new_photos = len(photos) - existing
        if new_photos == 0:
            console.print(f"  📁 [bold]{album_name}[/] — {len(photos)} photos (all cached)")
            return

        console.print(f"  📁 [bold]{album_name}[/] — {new_photos} new / {len(photos)} total")

        for i, photo_url in enumerate(photos, 1):
            ext = Path(photo_url).suffix or ".jpg"
            dest = album_dir / f"{i:04d}{ext}"
            self.download_photo(photo_url, dest)

    # ── top-level runner ────────────────────────────────────────────

    def run(self, username: str | None = None, password: str | None = None) -> None:
        """Authenticate and download all albums."""
        self.login(username, password)

        console.print("\n[bold]Scanning album pages…[/]")
        pages = self._fetch_album_pages()
        console.print(f"  Found {len(pages)} page(s)\n")

        all_albums: list[tuple[str, str, str]] = []
        for page_url in pages:
            all_albums.extend(self._parse_albums_from_page(page_url))

        console.print(f"[bold]Found {len(all_albums)} album(s)[/]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading…", total=len(all_albums))
            for album_url, name, desc in all_albums:
                self.download_album(album_url, name, desc)
                progress.advance(task)

        console.print(f"\n[green bold]✓ Done! Photos saved to {self.download_dir.resolve()}[/]")
