import json

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


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.setenv("BUCKET", "bkt")
    monkeypatch.setenv("PRINTERS", "office-1,lab")
    monkeypatch.setenv("IOT_ENDPOINT", "iot.example")
    s3, iot = FakeS3(), FakeIot()
    monkeypatch.setattr(handler, "_s3", lambda: s3)
    monkeypatch.setattr(handler, "_iot", lambda: iot)
    return s3, iot


def api_event(body, key="secret"):
    return {"headers": {"X-Api-Key": key}, "body": json.dumps(body)}


def test_rejects_bad_api_key(env):
    r = handler.handler(api_event({"printer_id": "lab", "filename": "a.pdf"}, key="nope"))
    assert r["statusCode"] == 401


def test_unknown_printer(env):
    r = handler.handler(api_event({"printer_id": "evil", "filename": "a.pdf"}))
    assert r["statusCode"] == 404


def test_bad_extension(env):
    r = handler.handler(api_event({"printer_id": "lab", "filename": "a.exe"}))
    assert r["statusCode"] == 400


def test_issues_upload_url(env):
    r = handler.handler(api_event({"printer_id": "lab", "filename": "Doc.PDF"}))
    body = json.loads(r["body"])
    assert r["statusCode"] == 200
    assert body["upload_url"].startswith("https://s3.example/put_object/jobs/lab/")
    assert body["upload_url"].split("?")[0].endswith(".pdf")


def s3_event(key, size=100):
    return {"Records": [{"s3": {"object": {"key": key, "size": size}}}]}


def test_s3_event_publishes_to_printer_topic(env):
    _, iot = env
    r = handler.handler(s3_event("jobs/office-1/abc123.pdf"))
    assert r == {"dispatched": 1}
    topic, qos, payload = iot.published[0]
    assert topic == "printers/office-1/jobs"
    assert qos == 1
    assert payload["job_id"] == "abc123" and payload["ext"] == ".pdf"
    assert payload["url"].startswith("https://")


def test_s3_event_ignores_foreign_keys(env):
    _, iot = env
    assert handler.handler(s3_event("other/x.pdf"))["dispatched"] == 0
    assert handler.handler(s3_event("jobs/a+b/x.pdf"))["dispatched"] == 0
    assert iot.published == []


def test_oversized_object_is_deleted_not_sent(env):
    s3, iot = env
    handler.handler(s3_event("jobs/lab/big.pdf", size=handler.MAX_BYTES + 1))
    assert s3.deleted == ["jobs/lab/big.pdf"]
    assert iot.published == []
