# LabDesk — WhatsApp Setup (wuzapi gateway)

LabDesk sends report PDFs over WhatsApp through a small, **free** self-hosted
gateway called **wuzapi** (https://github.com/asternic/wuzapi). The flow is:

```
LabDesk  ──HTTP──►  wuzapi (Docker container)  ──►  WhatsApp (linked phone)
```

> **Why wuzapi and not WAHA?** WAHA's free tier **cannot send file attachments**
> (that's a paid feature). wuzapi is MIT‑licensed, sends PDFs for free, and runs
> on SQLite with **no extra database**.

You set this up **once** on the lab's computer. After that LabDesk just talks to
`http://localhost:8080`.

> ⚠️ This links to WhatsApp like "WhatsApp Web" (a linked device). Use the lab's
> own number, send real reports (not bulk marketing), and you'll be fine.

---

## 1. Install Docker (one time)

**AlmaLinux / RHEL / Rocky (production):**
```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf -y install docker-ce docker-ce-cli containerd.io
sudo systemctl enable --now docker
sudo usermod -aG docker $USER          # run docker without sudo
```
**Arch Linux:** `sudo pacman -S --noconfirm docker && sudo systemctl enable --now docker && sudo usermod -aG docker $USER`

**Log out and back in once**, then verify: `docker ps` (empty table, no error).

---

## 2. Run wuzapi (one time)

Pick a strong admin token. The two encryption keys must be **exactly 32
characters** and **kept forever** (changing them logs WhatsApp out).

```bash
docker run -d \
  --name wuzapi \
  --restart unless-stopped \
  -p 8080:8080 \
  -e WUZAPI_ADMIN_TOKEN='CHANGE-ME-admin-token' \
  -e WUZAPI_GLOBAL_ENCRYPTION_KEY='32-char-encryption-key-keep-safe!' \
  -e WUZAPI_GLOBAL_HMAC_KEY='32-char-hmac-key-also-keep-safe!!' \
  -e TZ=Asia/Karachi \
  -v wuzapi-data:/app/dbdata \
  asternic/wuzapi
```
- `--restart unless-stopped` → starts automatically after a reboot.
- `-v wuzapi-data:/app/dbdata` + the fixed keys → **saves the WhatsApp login**, so
  you don't re‑scan after a restart.

Check: `docker ps` (STATUS "Up …"). Logs: `docker logs -f wuzapi`.

---

## 3. Create the LabDesk user (one time)

This makes the **access token** LabDesk will use. Replace the admin token with
yours from step 2, and pick any value for the user token.

```bash
curl -X POST http://localhost:8080/admin/users \
  -H "Authorization: CHANGE-ME-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"name":"LabDesk","token":"CHANGE-ME-user-token","events":"Message"}'
```
Keep **`CHANGE-ME-user-token`** — that's the **Access token** for LabDesk.

---

## 4. Link the lab's WhatsApp phone (scan the QR)

Easiest: open **http://localhost:8080/login** in a browser, paste the **user
token** from step 3, and a **QR code** appears.

On the lab phone: **WhatsApp → Settings → Linked Devices → Link a Device → scan.**

It links in a few seconds. (Don't disconnect/regenerate while scanning — scan the
QR that's shown and leave it.)

---

## 5. Configure LabDesk

**Settings → WhatsApp gateway:**

| Field | Value |
|---|---|
| Gateway URL | `http://localhost:8080` (use `https://…` if the gateway is on another computer — see security note) |
| Access token | the **user token** from step 3 |
| Country code | `92` |
| Auto‑send report (checkbox) | tick to send the report automatically when results are saved |
| Auto‑send bill (checkbox) | tick to send the cash receipt automatically when a bill is saved |

Click **Save settings**, then **Test connection** → it should say
*"Gateway reachable — WhatsApp is linked and ready."*

> **Consent:** reports/bills are only sent to patients who have agreed. Each
> patient has a **"Send reports & bills on WhatsApp"** toggle in **Reception**
> (on by default, recorded with a timestamp). Untick it and nothing is sent to
> that patient.

---

## 6. Send a report

- **Manual:** Worklist/Results → open a receipt with results → **Send WhatsApp**.
- **Automatic:** if you ticked auto‑send, it goes out when results are saved.

The report PDF is sent to the patient's saved number (stored as `03XXXXXXXXX`;
LabDesk converts it to `92XXXXXXXXXX` automatically).

---

## Everyday operations

| Task | Command |
|---|---|
| Is it running? | `docker ps` |
| Logs | `docker logs -f wuzapi` |
| Restart | `docker restart wuzapi` |
| Phone unlinked? | open `http://localhost:8080/login`, paste the user token, re‑scan |
| Update wuzapi | `docker pull asternic/wuzapi && docker rm -f wuzapi &&` *(re‑run step 2)* — the volume + keys keep you logged in |

wuzapi auto‑starts on boot, so normally you do nothing.

---

## Troubleshooting

- **"Test connection" → token wrong / Unauthorized** → the Access token in LabDesk
  must equal the **user token** from step 3 (sent as the `token` header).
- **"WhatsApp isn't linked — scan the QR"** → open `http://localhost:8080/login`,
  paste the user token, scan.
- **Reports don't arrive** → status must show **logged in**; re‑scan. Check the
  patient's number is correct.
- **Logged out after a restart** → you changed (or didn't set) the two 32‑char
  keys, or deleted the `wuzapi-data` volume. Keep both stable.
- **Gateway on another PC** → set LabDesk's Gateway URL to that PC and open its
  port. Prefer **`https://`** (e.g. behind a reverse proxy) — over plain
  `http://` the patient PDF *and* your access token travel the network
  unencrypted. LabDesk **warns** before saving a plain‑`http` URL that points
  anywhere other than this same computer.

---

## Notes

- wuzapi is free/open‑source (MIT) and enough for one lab.
- Don't expose port 8080 to the public internet without a firewall; the user
  token is what protects it.
- **Privacy:** delivery goes through WhatsApp (Meta), so reports/bills transit a
  third party. Send only to consenting patients (the per‑patient toggle in
  Reception) and cover WhatsApp delivery in your privacy policy.
- **Token storage:** the access token is kept in a private `0600`
  `~/.local/share/LabDesk/.secrets.json` file — never in the database or its
  backups, and never logged.
- `app/src/labdesk/whatsapp.py` is the only code that talks to the gateway —
  it posts to `/chat/send/document` with the `token` header, refuses cross‑host
  redirects, and confirms delivery from the gateway's JSON reply.
