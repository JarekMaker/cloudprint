"""Ways to hand a downloaded file to a physical printer."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path

Backend = Callable[[Path], str]


def dry_run(outdir: Path) -> Backend:
    """Keep the file instead of printing. Useful for testing the whole pipeline."""

    def run(path: Path) -> str:
        outdir.mkdir(parents=True, exist_ok=True)
        target = outdir / path.name
        shutil.copyfile(path, target)
        return f"saved to {target}"

    return run


def cups(printer: str | None) -> Backend:
    """Linux/macOS: use the `lp` client. No CUPS server config is required beyond the driver."""

    def run(path: Path) -> str:
        if not shutil.which("lp"):
            raise RuntimeError("`lp` not found; install cups-client")
        cmd = ["lp", "-t", path.stem]
        if printer:
            cmd += ["-d", printer]
        cmd.append(str(path))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "lp failed")
        return result.stdout.strip()

    return run


def raw(host: str, port: int = 9100) -> Backend:
    """Send bytes straight to a network printer (JetDirect/AppSocket).

    Works when the printer natively understands the file (PDF on most modern printers, plain text).
    """

    def run(path: Path) -> str:
        with socket.create_connection((host, port), timeout=10) as sock, path.open("rb") as fh:
            while chunk := fh.read(64 * 1024):
                sock.sendall(chunk)
        return f"sent {path.stat().st_size} bytes to {host}:{port}"

    return run


def windows() -> Backend:
    """Windows: print with the default application to the default printer."""

    def run(path: Path) -> str:
        if os.name != "nt":
            raise RuntimeError("windows backend only works on Windows")
        os.startfile(str(path), "print")  # type: ignore[attr-defined]
        return "sent to default printer"

    return run


def get_backend(
    name: str,
    *,
    cups_printer: str | None = None,
    host: str | None = None,
    port: int = 9100,
    outdir: Path = Path("received"),
) -> Backend:
    if name == "dry-run":
        return dry_run(outdir)
    if name == "cups":
        return cups(cups_printer)
    if name == "raw":
        if not host:
            raise ValueError("raw backend needs --printer-host")
        return raw(host, port)
    if name == "windows":
        return windows()
    raise ValueError(f"unknown backend: {name}")
