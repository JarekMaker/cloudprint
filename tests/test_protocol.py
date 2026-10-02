import json

import pytest

from cloudprint import protocol


def test_topics():
    assert protocol.jobs_topic("office-1") == "printers/office-1/jobs"
    assert protocol.status_topic("office-1") == "printers/office-1/status"


@pytest.mark.parametrize("bad", ["", "a/b", "a#", "x" * 41, "a+b", "../x"])
def test_topic_rejects_wildcards_and_traversal(bad):
    with pytest.raises(ValueError):
        protocol.jobs_topic(bad)


def test_content_type():
    assert protocol.content_type_for("Report.PDF") == "application/pdf"
    with pytest.raises(ValueError):
        protocol.content_type_for("virus.exe")
    with pytest.raises(ValueError):
        protocol.content_type_for("noext")


def _msg(**over):
    base = {"job_id": "abc123", "ext": ".pdf", "url": "https://bucket.s3.amazonaws.com/x"}
    base.update(over)
    return json.dumps(base)


def test_parse_job_ok():
    job = protocol.parse_job(_msg())
    assert (job.job_id, job.ext) == ("abc123", ".pdf")


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        _msg(job_id="../../etc"),
        _msg(ext=".exe"),
        _msg(url="http://insecure/x"),
        _msg(url="file:///etc/passwd"),
        json.dumps({"job_id": "a"}),
    ],
)
def test_parse_job_rejects(payload):
    with pytest.raises(ValueError):
        protocol.parse_job(payload)
