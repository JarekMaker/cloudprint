"""Lambda behind the HTTP API, the S3 trigger and the printer status rule.

Order lifecycle (DynamoDB `state`):
  paid -> queued -> received -> printed | failed

  POST /jobs        CLI, protected by API key
  POST /orders      kiosk page, protected by a per-printer token
  GET  /orders/{id} kiosk page polls the state
  S3 ObjectCreated  a paid order whose file arrived is pushed to printers/<id>/jobs
  IoT rule          printer status messages update the order
"""

import hmac
import json
import os
import re
import time
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
ORDER_TTL = 7 * 24 * 3600
PRINTER_STATES = {"received", "printed", "failed"}


@lru_cache
def _s3():
    return boto3.client("s3", config=Config(signature_version="s3v4"))


@lru_cache
def _iot():
    return boto3.client("iot-data", endpoint_url=f"https://{os.environ['IOT_ENDPOINT']}")


@lru_cache
def _table():
    return boto3.resource("dynamodb").Table(os.environ["ORDERS_TABLE"])


def _json(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _ext(filename):
    _, dot, ext = filename.rpartition(".")
    return f".{ext.lower()}" if dot else ""


def _same(a, b):
    return hmac.compare_digest(str(a).encode(), str(b).encode())


def _known_printer(printer_id):
    allowed = {p for p in os.environ.get("PRINTERS", "").split(",") if p}
    return isinstance(printer_id, str) and bool(ID_RE.fullmatch(printer_id)) and printer_id in allowed


def _get_order(job_id):
    return _table().get_item(Key={"job_id": job_id}).get("Item")


def _set_state(job_id, state, detail=""):
    _table().update_item(
        Key={"job_id": job_id},
        UpdateExpression="SET #s = :s, detail = :d",
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={":s": state, ":d": str(detail)[:200]},
    )


def handler(event, _context=None):
    if "Records" in event:
        return _on_s3(event)
    if "state" in event and "printer_id" in event:
        return _on_status(event)
    return _on_api(event)


def _on_api(event):
    route = event.get("routeKey")
    if route == "POST /jobs":
        return _create_job(event)
    if route == "POST /orders":
        return _create_order(event)
    if route == "GET /orders/{id}":
        return _read_order(event)
    return _json(404, {"error": "not found"})


def _body(event):
    try:
        data = json.loads(event.get("body") or "{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _new_order(printer_id, filename, source):
    ext = _ext(str(filename))
    if ext not in CONTENT_TYPES:
        return _json(400, {"error": f"unsupported file type: {ext or 'none'}"})

    job_id = uuid.uuid4().hex
    # Created as "paid" because there is no payment yet; a payment webhook will set this instead.
    _table().put_item(
        Item={
            "job_id": job_id,
            "printer_id": printer_id,
            "ext": ext,
            "state": "paid",
            "detail": "",
            "source": source,
            "expires": int(time.time()) + ORDER_TTL,
        }
    )
    url = _s3().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": os.environ["BUCKET"],
            "Key": f"jobs/{printer_id}/{job_id}{ext}",
            "ContentType": CONTENT_TYPES[ext],
        },
        ExpiresIn=UPLOAD_TTL,
    )
    return _json(200, {"job_id": job_id, "upload_url": url, "content_type": CONTENT_TYPES[ext]})


def _create_job(event):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if not _same(headers.get("x-api-key", ""), os.environ["API_KEY"]):
        return _json(401, {"error": "unauthorized"})
    body = _body(event)
    if not body or "printer_id" not in body or "filename" not in body:
        return _json(400, {"error": "printer_id and filename are required"})
    if not _known_printer(body["printer_id"]):
        return _json(404, {"error": "unknown printer"})
    return _new_order(body["printer_id"], body["filename"], "cli")


def _create_order(event):
    body = _body(event)
    if not body or "printer_id" not in body or "filename" not in body:
        return _json(400, {"error": "printer_id and filename are required"})
    printer_id = body["printer_id"]
    if not _known_printer(printer_id):
        return _json(403, {"error": "invalid kiosk link"})
    expected = json.loads(os.environ.get("KIOSK_TOKENS") or "{}").get(printer_id)
    if not expected or not _same(body.get("token", ""), expected):
        return _json(403, {"error": "invalid kiosk link"})
    return _new_order(printer_id, body["filename"], "kiosk")


def _read_order(event):
    job_id = (event.get("pathParameters") or {}).get("id", "")
    order = _get_order(job_id) if ID_RE.fullmatch(job_id) else None
    if not order:
        return _json(404, {"error": "unknown order"})
    return _json(200, {"state": order["state"], "detail": order.get("detail", "")})


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

        order = _get_order(job_id)
        if not order or order["state"] != "paid" or order["printer_id"] != printer_id:
            continue
        if record["s3"]["object"].get("size", 0) > MAX_BYTES:
            _s3().delete_object(Bucket=bucket, Key=key)
            _set_state(job_id, "failed", "file too large")
            continue

        url = _s3().generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=DOWNLOAD_TTL
        )
        _iot().publish(
            topic=f"printers/{printer_id}/jobs",
            qos=1,
            payload=json.dumps({"job_id": job_id, "ext": ext, "url": url}),
        )
        _set_state(job_id, "queued")
        dispatched += 1
    return {"dispatched": dispatched}


def _on_status(event):
    job_id, state = event.get("job_id"), event.get("state")
    if state not in PRINTER_STATES or not isinstance(job_id, str) or not ID_RE.fullmatch(job_id):
        return {"updated": False}
    order = _get_order(job_id)
    # printer_id comes from the MQTT topic, so a printer cannot touch another printer's orders
    if not order or order["printer_id"] != event["printer_id"]:
        return {"updated": False}
    _set_state(job_id, state, event.get("detail", ""))
    return {"updated": True}
