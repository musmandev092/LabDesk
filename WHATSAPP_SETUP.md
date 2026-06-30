# LabDesk — WhatsApp setup (wuzapi gateway)

LabDesk sends report/bill PDFs over WhatsApp through a small, free, self-hosted
gateway, **wuzapi** ([github.com/asternic/wuzapi](https://github.com/asternic/wuzapi)):

```
LabDesk ──HTTP──► wuzapi (Docker) ──► WhatsApp (linked phone)
```

Set up **once** on the lab PC; afterwards LabDesk just talks to `http://localhost:8080`.
This links WhatsApp like "WhatsApp Web" — use the lab's own number and send real
reports (not bulk marketing). (wuzapi is chosen over WAHA because WAHA's free tier
can't send file attachments; wuzapi is MIT-licensed and sends PDFs for free.)

> Run Docker commands with `sudo` (the user is intentionally not in the `docker`
> group). The tokens/keys below are samples — **change them** for a real deployment.

## 1. Install Docker (once)

```bash
# AlmaLinux / RHEL / Rocky:
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf -y install docker-ce docker-ce-cli containerd.io
sudo systemctl enable --now docker
sudo docker ps    # verify: empty table, no error
```

## 2. Run wuzapi (once)

```bash
sudo docker run -d --name wuzapi --restart unless-stopped -p 8080:8080 \
  -e 'WUZAPI_ADMIN_TOKEN=7d8F2xKmQ9vN5zPwB4rT6sE1vC8aX9zB' \
  -e 'DB_DIALECT=sqlite' \
  -e 'WUZAPI_GLOBAL_ENCRYPTION_KEY=e2a4b8c1d7f03e5a6b9c2d4e8f1a3b5c' \
  -e 'WUZAPI_GLOBAL_HMAC_KEY=9f1b3d5e7c0a2f4b6e8d0c2a4f6b8e0d' \
  -e 'TZ=Asia/Karachi' -v wuzapi-data:/app/dbdata asternic/wuzapi
```

`DB_DIALECT=sqlite` is **required** (so it builds its tables on first boot); the
`wuzapi-data` volume + fixed keys **persist the WhatsApp login** across reboots.
Check: `sudo docker ps` (STATUS "Up …"), `sudo docker logs -f wuzapi`.

## 3. Create the LabDesk user (once)

```bash
curl -X POST http://localhost:8080/admin/users \
  -H "Authorization: 7d8F2xKmQ9vN5zPwB4rT6sE1vC8aX9zB" -H "Content-Type: application/json" \
  -d '{"name":"LabDesk","token":"LD-prod-9a2b4c6d8e0f1a3b5c7d","events":"Message,ReadReceipt"}'
```

Keep the **user access token** (`LD-prod-9a2b4c6d8e0f1a3b5c7d`) safe.

## 4. Link the phone

Browse to `http://localhost:8080/login`, paste the user token → a QR appears. On the
lab phone: **WhatsApp → Settings → Linked Devices → Link a Device → scan**.

## 5. Configure LabDesk (Settings → WhatsApp gateway)

| Field | Value |
|---|---|
| Gateway URL | `http://localhost:8080` (use `https://…` if remote) |
| Access token | `LD-prod-9a2b4c6d8e0f1a3b5c7d` |
| Country code | `92` (digits only) |
| Auto-send report / bill | tick to send automatically on save |

**Save settings** → **Test connection** should reply "reachable / linked". Reports/bills
go only to patients with the **per-patient consent toggle** on (Reception, on by
default, timestamped).

## 6. Send

Manual: Worklist/Results → open a receipt with results → **Send WhatsApp**. Automatic:
on save if auto-send is ticked. Numbers stored as `03XXXXXXXXX` are converted to
`92XXXXXXXXXX` automatically.

## Everyday ops

| Task | Command |
|---|---|
| Running? | `sudo docker ps` |
| Logs | `sudo docker logs -f wuzapi` |
| Restart | `sudo docker restart wuzapi` |
| Phone unlinked? | open `…/login`, paste token, re-scan |
| Update | `sudo docker pull asternic/wuzapi && sudo docker rm -f wuzapi` then re-run step 2 |

## Troubleshooting

- **401 / token wrong** — the LabDesk Access token must exactly match the user token.
- **"WhatsApp isn't linked"** — re-pair at `…/login`.
- **Logged out after update/reboot** — the env keys changed, `DB_DIALECT` was missed,
  or the `wuzapi-data` volume was deleted; redo step 2 exactly.
- **Gateway on another PC** — set the URL to that machine's IP and expose 8080; prefer
  **`https://`** (e.g. behind nginx) or tokens + patient PDFs cross the LAN in clear.
  LabDesk warns before saving a plain-`http` URL pointing off-`localhost`.

## Notes

- Don't expose port 8080 to the open internet without a firewall rule — the token is
  your perimeter.
- Delivery transits WhatsApp (Meta); send only to consenting patients and cover it in
  your privacy policy.
- The token is stored in a `0600` `~/.local/share/LabDesk/.secrets.json` — never in
  the DB/backups, never logged. `src/labdesk/whatsapp.py` is the only code that talks
  to the gateway (posts to `/chat/send/document`, refuses cross-host redirects).
