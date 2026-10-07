"""Language data cannot be installed without the pinned digest and bounded transport."""

import hashlib
import importlib.util
from pathlib import Path

import httpx
import pytest
import respx


def load_setup():
    spec = importlib.util.spec_from_file_location("ocr_setup", "scripts/setup_ocr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@respx.mock
def test_pinned_model_install_and_skip_verified(tmp_path, monkeypatch):
    setup = load_setup()
    data = b"synthetic model test"
    monkeypatch.setattr(setup, "MODELS", {"kor": hashlib.sha256(data).hexdigest()})
    route = respx.get(
        f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{setup.COMMIT}/kor.traineddata"
    ).mock(return_value=httpx.Response(200, content=data))
    setup.install(tmp_path)
    setup.install(tmp_path)
    assert route.call_count == 1
    assert (tmp_path / "kor.traineddata").read_bytes() == data


@respx.mock
@pytest.mark.parametrize("response", [httpx.Response(200, content=b"wrong"), httpx.Response(302)])
def test_model_integrity_or_redirect_failure_preserves_existing(tmp_path: Path, response):
    setup = load_setup()
    target = tmp_path / "kor.traineddata"
    target.write_bytes(b"old model")
    respx.get(
        f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{setup.COMMIT}/kor.traineddata"
    ).mock(return_value=response)
    with pytest.raises((ValueError, httpx.HTTPError)):
        setup.install(tmp_path)
    assert target.read_bytes() == b"old model"
