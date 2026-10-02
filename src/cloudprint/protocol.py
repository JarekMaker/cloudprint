"""Message contract shared by the client, the agent and (duplicated) the Lambda."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
MAX_BYTES = 20 * 1024 * 1024
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def valid_id(value: str) -> bool:
    return bool(ID_RE.fullmatch(value))


def jobs_topic(printer_id: str) -> str:
    if not valid_id(printer_id):
        raise ValueError(f"invalid printer id: {printer_id!r}")
    return f"printers/{printer_id}/jobs"


def status_topic(printer_id: str) -> str:
    if not valid_id(printer_id):
        raise ValueError(f"invalid printer id: {printer_id!r}")
    return f"printers/{printer_id}/status"


def content_type_for(filename: str) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    try:
        return CONTENT_TYPES[ext]
    except KeyError:
        raise ValueError(f"unsupported file type: {ext or filename!r}") from None


@dataclass(frozen=True)
class Job:
    job_id: str
    ext: str
    url: str


def parse_job(payload: bytes | str) -> Job:
    """Parse and validate a job message received from the cloud."""
    try:
        data = json.loads(payload)
        job_id, ext, url = data["job_id"], data["ext"], data["url"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"malformed job message: {exc}") from exc
    if not isinstance(job_id, str) or not valid_id(job_id):
        raise ValueError("invalid job_id")
    if ext not in CONTENT_TYPES:
        raise ValueError(f"unsupported extension: {ext!r}")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError("job url must be https")
    return Job(job_id=job_id, ext=ext, url=url)
