"""Start a persistent local API without requiring Docker."""

import argparse
import os

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--backend", choices=["sqlite", "postgres"], default="sqlite")
    parser.add_argument("--read-only", action="store_true", help="Disable local review tools")
    args = parser.parse_args()
    os.environ["STORAGE_BACKEND"] = args.backend
    os.environ["LOCAL_MANAGEMENT_ENABLED"] = "false" if args.read_only else "true"
    uvicorn.run("sme_bridge.main:app", host="127.0.0.1", port=args.port)
