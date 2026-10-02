"""CLI to send a file to a printer from anywhere."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

from . import protocol


def send(path: Path, printer_id: str, api_url: str, api_key: str) -> str:
    if path.stat().st_size > protocol.MAX_BYTES:
        raise ValueError("file exceeds 20 MB limit")
    content_type = protocol.content_type_for(path.name)

    resp = requests.post(
        f"{api_url.rstrip('/')}/jobs",
        json={"printer_id": printer_id, "filename": path.name},
        headers={"x-api-key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    info = resp.json()

    with path.open("rb") as fh:
        put = requests.put(
            info["upload_url"], data=fh, headers={"Content-Type": content_type}, timeout=60
        )
    put.raise_for_status()
    return info["job_id"]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="cloudprint", description="Send a file to a remote printer")
    p.add_argument("file", type=Path)
    p.add_argument("--printer", required=True, help="printer id, e.g. office-1")
    p.add_argument("--api-url", default=os.getenv("CLOUDPRINT_API_URL"))
    p.add_argument("--api-key", default=os.getenv("CLOUDPRINT_API_KEY"))
    args = p.parse_args(argv)

    if not args.api_url or not args.api_key:
        sys.exit("set CLOUDPRINT_API_URL and CLOUDPRINT_API_KEY (or pass --api-url/--api-key)")
    try:
        job_id = send(args.file, args.printer, args.api_url, args.api_key)
    except (ValueError, OSError, requests.RequestException) as exc:
        sys.exit(f"error: {exc}")
    print(f"queued job {job_id} for {args.printer}")


if __name__ == "__main__":
    main()
