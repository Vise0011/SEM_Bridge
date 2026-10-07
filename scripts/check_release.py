"""Scan publishable files for local data and configured secrets without printing values."""

import subprocess
from pathlib import Path

from sme_bridge.config import Settings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    files = sorted(set(listing.rstrip("\0").split("\0")))
    settings = Settings(storage_backend="sqlite")
    secrets = [
        value.get_secret_value()
        for value in [settings.bizinfo_api_key, settings.postgres_password, settings.neo4j_password]
        if value is not None
        and value.get_secret_value()
        and not value.get_secret_value().startswith("replace-")
        and value.get_secret_value() not in {"sme_bridge", "change-me", "test-password"}
    ]
    failures = []
    for relative in files:
        path = root / relative
        normalized = relative.replace("\\", "/")
        if (path.name.startswith(".env") and path.name != ".env.example") or (
            normalized.startswith(("data/local/", "artifacts/"))
            or path.suffix in {".sqlite3", ".traineddata"}
        ):
            failures.append(f"Private artifact in publishable files: {relative}")
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(secret in content for secret in secrets):
            failures.append(f"Configured private value found in: {relative}")
    for relative in [".env", "data/local/bridge.sqlite3", "artifacts/qa/validation-report.md"]:
        result = subprocess.run(["git", "check-ignore", "-q", relative], cwd=root)
        if result.returncode != 0:
            failures.append(f"Missing ignore rule: {relative}")
    if failures:
        print("\n".join(failures))
        return 1
    print(
        f"Release scan: {len(files)} files checked; private artifacts ignored; "
        "no configured secrets found"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
