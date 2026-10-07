"""Download hash-pinned official Tesseract language data inside the ignored project data."""

import hashlib
import os
import tempfile
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
            with client.stream("GET", url) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 8 * 1024 * 1024:
                        raise ValueError("OCR model exceeds size limit")
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


if __name__ == "__main__":
    from sme_bridge.config import Settings

    try:
        install(Path(Settings().ocr_tessdata_path))
    except (httpx.HTTPError, ValueError, OSError):
        raise SystemExit(
            "OCR setup failed: check network, writable path and model integrity."
        ) from None
