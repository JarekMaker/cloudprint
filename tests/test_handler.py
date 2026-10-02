import json
from types import SimpleNamespace

import handler
import pytest


class FakeS3:
    def __init__(self):
        self.deleted = []

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://s3.example/{op}/{Params['Key']}?exp={ExpiresIn}"

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)


class FakeIot:
    def __init__(self):
        self.published = []

    def publish(self, topic, qos, payload):
        self.published.append((topic, qos, json.loads(payload)))


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[Item["job_id"]] = dict(Item)

    def get_item(self, Key):
        item = self.items.get(Key["job_id"])
        return {"Item": dict(item)} if item else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        item = self.items[Key["job_id"]]
        item["state"] = ExpressionAttributeValues[":s"]
        item["detail"] = ExpressionAttributeValues[":d"]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.setenv("BUCKET", "bkt")
    monkeypatch.setenv("PRINTERS", "office-1,lab")
    monkeypatch.setenv("IOT_ENDPOINT", "iot.example")
    monkeypatch.setenv("KIOSK_TOKENS", json.dumps({"office-1": "tok-1", "lab": "tok-2"}))
    fake = SimpleNamespace(s3=FakeS3(), iot=FakeIot(), table=FakeTable())
    monkeypatch.setattr(handler, "_s3", lambda: fake.s3)
    monkeypatch.setattr(handler, "_iot", lambda: fake.iot)
    monkeypatch.setattr(handler, "_table", lambda: fake.table)
    return fake


def job_event(body, key="secret"):
    return {"routeKey": "POST /jobs", "headers": {"X-Api-Key": key}, "body": json.dumps(body)}


def order_event(body):
    return {"routeKey": "POST /orders", "body": json.dumps(body)}


def seed(env, job_id, printer="lab", state="paid"):
    env.table.put_item(
        Item={"job_id": job_id, "printer_id": printer, "ext": ".pdf", "state": state, "detail": ""}
    )


def test_unknown_route(env):
    assert handler.handler({"routeKey": "GET /nope"})["statusCode"] == 404


def test_jobs_rejects_bad_api_key(env):
    r = handler.handler(job_event({"printer_id": "lab", "filename": "a.pdf"}, key="nope"))
    assert r["statusCode"] == 401


def test_jobs_unknown_printer(env):
    r = handler.handler(job_event({"printer_id": "evil", "filename": "a.pdf"}))
    assert r["statusCode"] == 404


def test_jobs_bad_extension(env):
    r = handler.handler(job_event({"printer_id": "lab", "filename": "a.exe"}))
    assert r["statusCode"] == 400


def test_jobs_issues_upload_url_and_records_order(env):
    r = handler.handler(job_event({"printer_id": "lab", "filename": "Doc.PDF"}))
    body = json.loads(r["body"])
    assert r["statusCode"] == 200
    assert body["upload_url"].startswith("https://s3.example/put_object/jobs/lab/")
    assert body["upload_url"].split("?")[0].endswith(".pdf")
    assert env.table.items[body["job_id"]]["state"] == "paid"


def test_order_needs_valid_token(env):
    bad = handler.handler(order_event({"printer_id": "lab", "filename": "a.pdf", "token": "tok-1"}))
    assert bad["statusCode"] == 403
    missing = handler.handler(order_event({"printer_id": "lab", "filename": "a.pdf"}))
    assert missing["statusCode"] == 403
    unknown = handler.handler(order_event({"printer_id": "x", "filename": "a.pdf", "token": "t"}))
    assert unknown["statusCode"] == 403


def test_order_with_token_creates_kiosk_order(env):
    r = handler.handler(order_event({"printer_id": "lab", "filename": "a.png", "token": "tok-2"}))
    body = json.loads(r["body"])
    assert r["statusCode"] == 200
    assert env.table.items[body["job_id"]]["source"] == "kiosk"


def test_read_order(env):
    seed(env, "abc123", state="printed")
    ok = handler.handler({"routeKey": "GET /orders/{id}", "pathParameters": {"id": "abc123"}})
    assert json.loads(ok["body"]) == {"state": "printed", "detail": ""}
    missing = handler.handler({"routeKey": "GET /orders/{id}", "pathParameters": {"id": "nope"}})
    assert missing["statusCode"] == 404


def s3_event(key, size=100):
    return {"Records": [{"s3": {"object": {"key": key, "size": size}}}]}


def test_s3_event_publishes_paid_order_and_marks_queued(env):
    seed(env, "abc123", printer="office-1")
    r = handler.handler(s3_event("jobs/office-1/abc123.pdf"))
    assert r == {"dispatched": 1}
    topic, qos, payload = env.iot.published[0]
    assert topic == "printers/office-1/jobs"
    assert qos == 1
    assert payload["job_id"] == "abc123" and payload["ext"] == ".pdf"
    assert payload["url"].startswith("https://")
    assert env.table.items["abc123"]["state"] == "queued"


def test_s3_event_ignores_unpaid_or_unknown_orders(env):
    seed(env, "unpaid1", state="created")
    assert handler.handler(s3_event("jobs/lab/unpaid1.pdf"))["dispatched"] == 0
    assert handler.handler(s3_event("jobs/lab/ghost.pdf"))["dispatched"] == 0
    assert env.iot.published == []


def test_s3_event_rejects_printer_mismatch(env):
    seed(env, "abc123", printer="lab")
    assert handler.handler(s3_event("jobs/office-1/abc123.pdf"))["dispatched"] == 0


def test_s3_event_ignores_foreign_keys(env):
    assert handler.handler(s3_event("other/x.pdf"))["dispatched"] == 0
    assert handler.handler(s3_event("jobs/a+b/x.pdf"))["dispatched"] == 0
    assert env.iot.published == []


def test_oversized_object_is_deleted_and_order_failed(env):
    seed(env, "big", printer="lab")
    handler.handler(s3_event("jobs/lab/big.pdf", size=handler.MAX_BYTES + 1))
    assert env.s3.deleted == ["jobs/lab/big.pdf"]
    assert env.iot.published == []
    assert env.table.items["big"]["state"] == "failed"


def test_status_message_updates_order(env):
    seed(env, "abc123", printer="lab", state="queued")
    r = handler.handler({"job_id": "abc123", "state": "printed", "detail": "ok", "printer_id": "lab"})
    assert r == {"updated": True}
    assert env.table.items["abc123"]["state"] == "printed"


def test_status_from_other_printer_is_ignored(env):
    seed(env, "abc123", printer="lab", state="queued")
    r = handler.handler({"job_id": "abc123", "state": "printed", "printer_id": "office-1"})
    assert r == {"updated": False}
    assert env.table.items["abc123"]["state"] == "queued"


def test_online_offline_messages_are_ignored(env):
    assert handler.handler({"state": "online", "printer_id": "lab"}) == {"updated": False}
