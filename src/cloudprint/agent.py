"""Agent that runs next to a printer, listens on AWS IoT Core and prints incoming jobs."""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import tempfile
import threading
from pathlib import Path

import paho.mqtt.client as mqtt
import requests

from . import protocol
from .backends import Backend, get_backend

log = logging.getLogger("cloudprint.agent")


def download(url: str, dest: Path) -> None:
    """Stream a presigned URL to disk, enforcing the size limit."""
    size = 0
    with requests.get(url, stream=True, timeout=30) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(64 * 1024):
                size += len(chunk)
                if size > protocol.MAX_BYTES:
                    raise ValueError("file too large")
                fh.write(chunk)


class Agent:
    def __init__(self, printer_id: str, backend: Backend):
        self.printer_id = printer_id
        self.backend = backend
        self.jobs: queue.Queue[protocol.Job] = queue.Queue()
        self.client: mqtt.Client | None = None

    def report(self, job_id: str | None, state: str, detail: str = "") -> None:
        log.info("job=%s state=%s %s", job_id, state, detail)
        if self.client is None:
            return
        body = json.dumps({"job_id": job_id, "state": state, "detail": detail})
        self.client.publish(protocol.status_topic(self.printer_id), body, qos=1)

    def process(self, job: protocol.Job) -> None:
        self.report(job.job_id, "received")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{job.job_id}{job.ext}"
            try:
                download(job.url, path)
                detail = self.backend(path)
            except Exception as exc:  # noqa: BLE001 - every failure must be reported to the cloud
                self.report(job.job_id, "failed", str(exc))
                return
        self.report(job.job_id, "printed", detail)

    def worker(self) -> None:
        # Printing happens off the MQTT thread so keep-alives are never blocked.
        while True:
            self.process(self.jobs.get())

    def on_connect(self, client, _userdata, _flags, reason_code, _props) -> None:
        if reason_code.is_failure:
            log.error("connect failed: %s", reason_code)
            return
        client.subscribe(protocol.jobs_topic(self.printer_id), qos=1)
        client.publish(protocol.status_topic(self.printer_id), '{"state":"online"}', qos=1, retain=True)
        log.info("connected, waiting for jobs on %s", protocol.jobs_topic(self.printer_id))

    def on_message(self, _client, _userdata, msg) -> None:
        try:
            job = protocol.parse_job(msg.payload)
        except ValueError as exc:
            self.report(None, "rejected", str(exc))
            return
        self.jobs.put(job)

    def run(self, endpoint: str, ca: str, cert: str, key: str) -> None:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.printer_id,
            clean_session=False,
        )
        client.tls_set(ca_certs=ca, certfile=cert, keyfile=key)
        client.will_set(
            protocol.status_topic(self.printer_id), '{"state":"offline"}', qos=1, retain=True
        )
        client.reconnect_delay_set(min_delay=1, max_delay=60)
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        self.client = client
        threading.Thread(target=self.worker, daemon=True).start()
        client.connect_async(endpoint, 8883, keepalive=30)
        client.loop_forever()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="CloudPrint agent")
    p.add_argument("--printer-id", default=os.getenv("PRINTER_ID"), required=not os.getenv("PRINTER_ID"))
    p.add_argument("--endpoint", default=os.getenv("IOT_ENDPOINT"), required=not os.getenv("IOT_ENDPOINT"))
    p.add_argument("--certs", default=os.getenv("CERTS_DIR", "certs"), help="dir with cert.pem, key.pem, AmazonRootCA1.pem")
    p.add_argument("--backend", default=os.getenv("BACKEND", "dry-run"), choices=["dry-run", "cups", "raw", "windows"])
    p.add_argument("--cups-printer", default=os.getenv("CUPS_PRINTER"))
    p.add_argument("--printer-host", default=os.getenv("PRINTER_HOST"))
    p.add_argument("--printer-port", type=int, default=int(os.getenv("PRINTER_PORT", "9100")))
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    backend = get_backend(
        args.backend, cups_printer=args.cups_printer, host=args.printer_host, port=args.printer_port
    )
    certs = Path(args.certs)
    Agent(args.printer_id, backend).run(
        args.endpoint,
        ca=str(certs / "AmazonRootCA1.pem"),
        cert=str(certs / "cert.pem"),
        key=str(certs / "key.pem"),
    )


if __name__ == "__main__":
    main()
