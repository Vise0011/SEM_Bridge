"""Download hash-pinned official Tesseract language data inside the ignored project data."""

import hashlib
import os
import tempfile
import time
from pathlib import Path

import httpx

COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
MODELS = {
    "kor": "6b85e11d9bbf07863b97b3523b1b112844c43e713df8b66418a081fd1060b3b2",
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
}


def install(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        for language, checksum in MODELS.items():
            target = destination / f"{language}.traineddata"
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == checksum:
                print(f"{language}: verified, already installed")
                continue
            url = (
                "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/"
                f"{COMMIT}/{language}.traineddata"
            )
            data = bytearray()
            for attempt in range(3):
                data = bytearray()
                try:
                    with client.stream("GET", url) as response:
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            data.extend(chunk)
                            if len(data) > 8 * 1024 * 1024:
                                raise ValueError("OCR model exceeds size limit")
                    break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                        raise
                except httpx.RequestError:
                    if attempt == 2:
                        raise
                time.sleep(attempt + 1)
            if hashlib.sha256(data).hexdigest() != checksum:
                raise ValueError("OCR model checksum mismatch")
            # Atomic install: partial downloads never replace a usable model.
            with tempfile.NamedTemporaryFile(dir=destination, delete=False) as temporary:
                temporary.write(data)
                temporary_path = Path(temporary.name)
            try:
                os.replace(temporary_path, target)
            finally:
                temporary_path.unlink(missing_ok=True)
            print(f"{language}: installed and verified")


def main() -> int:
    from sme_bridge.config import Settings

    try:
        # Downloading language data does not require database credentials or connections.
        install(Path(Settings(storage_backend="sqlite").ocr_tessdata_path))
    except httpx.HTTPStatusError as exc:
        print(f"OCR setup failed: upstream HTTP {exc.response.status_code}.")
        return 1
    except (httpx.HTTPError, ValueError, OSError) as exc:
        print(
            f"OCR setup failed: {type(exc).__name__}; check network, writable path and integrity."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
