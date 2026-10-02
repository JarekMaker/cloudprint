import socket
import threading

import pytest

from cloudprint import backends


def test_dry_run_copies_file(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("hello")
    out = tmp_path / "out"
    msg = backends.get_backend("dry-run", outdir=out)(src)
    assert (out / "a.txt").read_text() == "hello"
    assert "saved" in msg


def test_raw_sends_bytes_to_port(tmp_path):
    received = bytearray()
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def serve():
        conn, _ = server.accept()
        with conn:
            while data := conn.recv(4096):
                received.extend(data)

    t = threading.Thread(target=serve)
    t.start()
    src = tmp_path / "job.txt"
    src.write_bytes(b"x" * 200_000)
    backends.get_backend("raw", host="127.0.0.1", port=port)(src)
    t.join(timeout=5)
    server.close()
    assert len(received) == 200_000


def test_raw_requires_host():
    with pytest.raises(ValueError):
        backends.get_backend("raw")


def test_unknown_backend():
    with pytest.raises(ValueError):
        backends.get_backend("fax")
