# CloudPrint

Send a document to **any printer from anywhere** through AWS, with **no local print server**.

```
 you ──► cloudprint CLI ──► API Gateway + Lambda ──► S3 (1-day expiry)
                                   │
                                   └──► AWS IoT Core (MQTT, mutual TLS)
                                                │
                                      agent next to the printer ──► prints
                                                │
                                      status (printed / failed) back to the cloud
```

A printer cannot speak to AWS by itself, so a tiny **agent** runs beside it (Raspberry Pi Zero,
an old PC, a container). It is not a print server: it keeps no queue and exposes no ports. It only
opens one outbound MQTT connection, so no router changes, VPN or port forwarding are needed.

## How it works

1. `cloudprint report.pdf --printer office-1` asks the API for an upload URL.
2. The API checks the API key and that the printer is known, then returns a presigned S3 `PUT` URL.
3. The file lands in S3, which triggers the Lambda. It publishes a presigned `GET` URL to
   `printers/office-1/jobs`.
4. The agent on that printer receives the message, downloads the file and hands it to a backend.
5. The agent reports `received` and then `printed` or `failed` on `printers/office-1/status`.
   Last-will messages make online/offline visible to the cloud.

If the printer is offline, MQTT QoS 1 with a persistent session delivers the job when it reconnects
(the download link is valid for one hour).

## Print backends

| Backend | Use when |
|---|---|
| `cups` | Linux/macOS/Raspberry Pi with the printer installed (`lp`) |
| `raw` | Network printer on port 9100 that accepts PDF/text natively |
| `windows` | Windows PC with a default printer |
| `dry-run` | Testing: saves files to `./received` |

## Deploy

Requirements: Terraform >= 1.5, AWS credentials, Python >= 3.10.

```bash
cd infra
terraform init
terraform apply -var 'printers=["office-1","lab"]'
cd ..
python scripts/export_credentials.py     # writes certs/<printer>/ and prints env vars
```

Set a budget alarm first. Idle cost is close to zero; the API is throttled to 5 req/s.
Remove everything with `terraform destroy`.

## Run an agent

```bash
pip install .
export IOT_ENDPOINT=xxxx-ats.iot.eu-central-1.amazonaws.com PRINTER_ID=office-1
export CERTS_DIR=certs/office-1 BACKEND=cups CUPS_PRINTER=HP_LaserJet
cloudprint-agent
```

Or with Docker: `docker run --rm -v $PWD/certs/office-1:/certs -e PRINTER_ID=office-1 -e IOT_ENDPOINT=... -e BACKEND=raw -e PRINTER_HOST=192.168.1.50 cloudprint-agent`

## Send a job

```bash
export CLOUDPRINT_API_URL=https://xxxx.execute-api.eu-central-1.amazonaws.com
export CLOUDPRINT_API_KEY=...
cloudprint invoice.pdf --printer office-1
```

## Kiosk mode (QR code at the printer)

A static page in `web/` lets anyone print without an account: scan the QR code on the printer,
choose a file, watch the status.

1. Set `window.CLOUDPRINT_API` in `web/config.js` to the `api_url` output.
2. Host `web/` anywhere static (GitHub Pages: Settings, Pages, deploy from the `web` folder).
3. `python scripts/export_credentials.py` prints one link per printer, like
   `<PAGE_URL>/?p=office-1&t=<token>`. Turn each into a QR code and stick it on the printer.

Every upload creates an order in DynamoDB that moves through
`paid -> queued -> received -> printed | failed`. The file is only sent to the printer when the
order is `paid`. Today orders are created as `paid` because there is no payment step; adding Stripe
means creating them as `created` and flipping to `paid` from the payment webhook.

## Security model

- Each printer has its own X.509 certificate. The IoT policy uses `${iot:Connection.Thing.ThingName}`,
  so a printer can only connect as itself and only touch its own two topics.
- The agent accepts only `https://` URLs, a fixed list of file extensions, validated IDs and a 20 MB
  limit. Files are written to a temp dir with a name it generates, never one from the message.
- Bucket is private, encrypted and objects expire after one day. Presigned URLs are short-lived.
- The Lambda role can only touch `jobs/*` and publish to `printers/*/jobs`.
- The public kiosk endpoint needs a per-printer token (carried by the QR link), is throttled, and
  rejects unknown printers. The token only lets you order for that one printer.
- Printer status is attributed using the MQTT topic, so a device cannot update another's orders.
- Known limitation: the kiosk token is a shared secret printed on a sticker, and there is no
  per-user rate limit yet. Payment would be the real abuse control.
- Known limitation: one shared API key for the CLI. Next step would be per-user auth (Cognito/JWT).
- Terraform state contains the device private keys, so use an encrypted remote backend for real use.

## Develop

```bash
pip install -e ".[dev]" boto3
ruff check . && pytest
```

## Roadmap

- Cognito auth instead of a shared API key
- Stripe Checkout (test mode first) as the `created -> paid` step
- Page counting and per-page pricing
- Alert when a printer goes offline
- Convert office documents to PDF before dispatch
- ESP32 variant for printers with a raw socket
