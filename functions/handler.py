"""Lambda: issues upload URLs and, once a file lands in S3, pushes the job to the printer over MQTT.

Flow:
  POST /jobs            -> validate API key + printer, return presigned PUT url
  S3 ObjectCreated      -> presign a GET url, publish it to printers/<id>/jobs
"""

import hmac
import json
import os
import re
import uuid
from functools import lru_cache
from urllib.parse import unquote_plus

import boto3
from botocore.config import Config

ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
MAX_BYTES = 20 * 1024 * 1024
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
UPLOAD_TTL = 300
DOWNLOAD_TTL = 3600  # lets a briefly offline printer still fetch queued jobs


@lru_cache
def _s3():
    return boto3.client("s3", config=Config(signature_version="s3v4"))


@lru_cache
def _iot():
    return boto3.client("iot-data", endpoint_url=f"https://{os.environ['IOT_ENDPOINT']}")


def _json(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _ext(filename):
    _, dot, ext = filename.rpartition(".")
    return f".{ext.lower()}" if dot else ""


def handler(event, _context=None):
    if "Records" in event:
        return _on_s3(event)
    return _on_api(event)


def _on_api(event):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if not hmac.compare_digest(headers.get("x-api-key", ""), os.environ["API_KEY"]):
        return _json(401, {"error": "unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
        printer_id, filename = body["printer_id"], body["filename"]
    except (ValueError, KeyError, TypeError):
        return _json(400, {"error": "printer_id and filename are required"})

    allowed = {p for p in os.environ.get("PRINTERS", "").split(",") if p}
    if not isinstance(printer_id, str) or not ID_RE.fullmatch(printer_id) or printer_id not in allowed:
        return _json(404, {"error": "unknown printer"})
    ext = _ext(str(filename))
    if ext not in CONTENT_TYPES:
        return _json(400, {"error": f"unsupported file type: {ext or 'none'}"})

    job_id = uuid.uuid4().hex
    key = f"jobs/{printer_id}/{job_id}{ext}"
    url = _s3().generate_presigned_url(
        "put_object",
        Params={"Bucket": os.environ["BUCKET"], "Key": key, "ContentType": CONTENT_TYPES[ext]},
        ExpiresIn=UPLOAD_TTL,
    )
    return _json(200, {"job_id": job_id, "upload_url": url, "content_type": CONTENT_TYPES[ext]})


def _on_s3(event):
    bucket = os.environ["BUCKET"]
    dispatched = 0
    for record in event["Records"]:
        key = unquote_plus(record["s3"]["object"]["key"])
        parts = key.split("/")
        if len(parts) != 3 or parts[0] != "jobs":
            continue
        printer_id = parts[1]
        job_id, ext = os.path.splitext(parts[2])
        if not (ID_RE.fullmatch(printer_id) and ID_RE.fullmatch(job_id) and ext in CONTENT_TYPES):
            continue
        if record["s3"]["object"].get("size", 0) > MAX_BYTES:
            _s3().delete_object(Bucket=bucket, Key=key)
            continue

        url = _s3().generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=DOWNLOAD_TTL
        )
        _iot().publish(
            topic=f"printers/{printer_id}/jobs",
            qos=1,
            payload=json.dumps({"job_id": job_id, "ext": ext, "url": url}),
        )
        dispatched += 1
    return {"dispatched": dispatched}
