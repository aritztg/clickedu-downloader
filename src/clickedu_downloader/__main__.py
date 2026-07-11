"""Entry point for the CLI."""

from clickedu_downloader import ClickeduDownloader


def main() -> None:
    downloader = ClickeduDownloader()
    downloader.run()


if __name__ == "__main__":
    main()
