"""Clickedu photo album downloader using curl_cffi."""

import os
import re
import getpass
from pathlib import Path
from datetime import datetime

import piexif
from curl_cffi import requests
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


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

        Args:
            username: Clickedu username. Prompts if not provided.
            password: Clickedu password. Prompts if not provided.
        """
        if not username:
            username = input("Clickedu username: ")
        if not password:
            password = getpass.getpass("Clickedu password: ")

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
    def _extract_datetime_from_filename(filename: str) -> datetime | None:
        """Try to extract a datetime from common filename patterns.

        Patterns: YYYYMMDD_HHMMSS, IMG_YYYYMMDD_HHMMSS, etc.
        """
        # Try ISO-ish patterns embedded in filenames
        patterns = [
            r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})",  # 20241005_143000
            r"(\d{4})-(\d{2})-(\d{2})[T _](\d{2})[.:](\d{2})",  # 2024-10-05 14:30
            r"(\d{4})(\d{2})(\d{2})[-_](\d{2})(\d{2})",  # 20241005-1430
        ]

        for pattern in patterns:
            match = re.search(pattern, filename)
            if match:
                groups = match.groups()
                try:
                    if len(groups) == 6:
                        return datetime(
                            int(groups[0]), int(groups[1]), int(groups[2]),
                            int(groups[3]), int(groups[4]), int(groups[5]),
                        )
                    elif len(groups) == 5:
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

        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt_str
        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = dt_str

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, str(image_path))

    # ── download ────────────────────────────────────────────────────

    def download_photo(self, photo_url: str, dest_path: Path) -> bool:
        """Download a single photo and set its EXIF date if missing.

        Returns:
            True on success, False on failure.
        """
        try:
            resp = self.session.get(photo_url, timeout=30, impersonate="chrome")  # type: ignore[union-attr]
            resp.raise_for_status()
        except Exception as exc:
            console.print(f"    [red]✗ download failed: {photo_url} — {exc}[/]")
            return False

        dest_path.write_bytes(resp.content)

        # Check for EXIF DateTimeOriginal
        try:
            exif = piexif.load(resp.content)
            has_date = piexif.ExifIFD.DateTimeOriginal in exif.get("Exif", {})
        except Exception:
            has_date = False

        if not has_date:
            dt = self._extract_datetime_from_filename(photo_url)
            if dt:
                try:
                    self._set_exif_datetime(dest_path, dt)
                except Exception:
                    pass  # non-critical

        return True

    def download_album(self, album_url: str, album_name: str, description: str = "") -> None:
        """Download all photos from a single album.

        Args:
            album_url: Full URL of the album page.
            album_name: Human-readable name (used as folder name).
            description: Album description to save as album_info.txt.
        """
        album_dir = self.download_dir / album_name
        album_dir.mkdir(parents=True, exist_ok=True)

        # Save description
        if description:
            (album_dir / "album_info.txt").write_text(description, encoding="utf-8")

        # Fetch album page
        resp = self.session.get(album_url, impersonate="chrome")  # type: ignore[union-attr]
        photos = self._extract_photos_from_album(resp.text)

        if not photos:
            console.print(f"  [yellow]⚠ no photos found in '{album_name}'[/]")
            return

        console.print(f"  📁 [bold]{album_name}[/] — {len(photos)} photos")

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
