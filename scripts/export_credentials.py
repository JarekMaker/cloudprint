"""Write each printer's certificate material to certs/<printer-id>/ from `terraform output`.

Usage (from repo root, after `terraform apply`):
    python scripts/export_credentials.py
Then copy certs/<printer-id>/ to the device running the agent.
"""

import json
import subprocess
import sys
from pathlib import Path

import requests

ROOT_CA_URL = "https://www.amazontrust.com/repository/AmazonRootCA1.pem"


def tf_output() -> dict:
    out = subprocess.run(
        ["terraform", "-chdir=infra", "output", "-json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def main() -> None:
    outputs = tf_output()
    root_ca = requests.get(ROOT_CA_URL, timeout=15)
    root_ca.raise_for_status()

    for printer_id, creds in outputs["printer_credentials"]["value"].items():
        folder = Path("certs") / printer_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "cert.pem").write_text(creds["cert"])
        key_file = folder / "key.pem"
        key_file.write_text(creds["key"])
        key_file.chmod(0o600)
        (folder / "AmazonRootCA1.pem").write_text(root_ca.text)
        print(f"wrote {folder}/")

    print("\nClient environment:")
    print(f"  CLOUDPRINT_API_URL={outputs['api_url']['value']}")
    print(f"  CLOUDPRINT_API_KEY={outputs['api_key']['value']}")
    print("Agent environment:")
    print(f"  IOT_ENDPOINT={outputs['iot_endpoint']['value']}")
    print("Kiosk page links (put your hosted web/ URL in front, then make a QR code):")
    for printer_id, query in outputs["kiosk_queries"]["value"].items():
        print(f"  {printer_id}: <PAGE_URL>/?{query}")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        sys.exit(f"terraform output failed: {exc}")
