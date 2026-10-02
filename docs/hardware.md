# Where does the agent run?

The agent needs a device on the same network or USB connection as the printer. It only makes
outbound connections (TCP 8883 to AWS IoT Core).

| Option | Cost | Printer connection | Backend |
|---|---|---|---|
| Raspberry Pi Zero 2 W | ~$15 | USB to a basic printer | `cups` |
| Old office PC / laptop | free | USB or network | `cups` or `windows` |
| Existing server or NAS container | free | network printer | `raw` |

Notes for salvaged printers:

- Old inkjets usually speak only a proprietary protocol, so use the OS driver through `cups`.
- `raw` works for printers that accept PDF or text directly on port 9100. Test with
  `nc <printer-ip> 9100 < test.txt` before configuring the agent.
- Use a plain printer for testing first; avoid anything under mains voltage that you opened.

## Pairing a device

1. Add the printer ID to `printers` in `infra` and run `terraform apply`.
2. `python scripts/export_credentials.py`
3. Copy `certs/<printer-id>/` to the device (`chmod 600 key.pem`).
4. Start the agent, or install it as a systemd service:

```ini
[Unit]
Description=CloudPrint agent
After=network-online.target

[Service]
Environment=PRINTER_ID=office-1 IOT_ENDPOINT=xxxx-ats.iot.eu-central-1.amazonaws.com
Environment=CERTS_DIR=/etc/cloudprint BACKEND=cups
ExecStart=/usr/local/bin/cloudprint-agent
Restart=always
User=cloudprint

[Install]
WantedBy=multi-user.target
```
