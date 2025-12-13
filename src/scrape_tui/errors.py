class ScrapeTuiError(Exception):
    pass


class UnsupportedUrlError(ScrapeTuiError):
    def __init__(self, url: str, message: str | None = None) -> None:
        super().__init__(message or f"Unsupported URL: {url}")
        self.url = url


class DownloadFailedError(ScrapeTuiError):
    pass

