# LabDesk — WhatsApp Setup (wuzapi gateway)

LabDesk sends report PDFs over WhatsApp through a small, **free** self-hosted gateway called **wuzapi** ([https://github.com/asternic/wuzapi](https://github.com/asternic/wuzapi)). The flow is:

```
LabDesk  ──HTTP──►  wuzapi (Docker container)  ──►  WhatsApp (linked phone)

```

> **Why wuzapi and not WAHA?** WAHA's free tier **cannot send file attachments** (that's a paid feature). wuzapi is MIT‑licensed, sends PDFs for free, and runs on SQLite with **no extra database**.

You set this up **once** on the lab's computer. After that LabDesk just talks to `http://localhost:8080`.

> ⚠️ This links to WhatsApp like "WhatsApp Web" (a linked device). Use the lab's own number, send real reports (not bulk marketing), and you'll be fine.

---

## 1. Install Docker (one time)

> 🔒 **Security Notice:** For maximum security, user accounts are intentionally **not** added to the `docker` root group. All Docker commands must be run explicitly with `sudo`.

**AlmaLinux / RHEL / Rocky (production):**

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf -y install docker-ce docker-ce-cli containerd.io
sudo systemctl enable --now docker

```

**Other Linux:** Ask your AI or search online: *"How do I install Docker on [Your OS Name] and then sudo systemctl enable --now docker?"*


Verify your installation:

```bash
sudo docker ps

```

*(Should output an empty table header with no error).*

---

## 2. Run wuzapi (one time)

Run this exact block to spin up the container.

*(Note: The Admin Token is purely alphanumeric to ensure Linux terminal shells like Bash or Zsh do not manipulate or truncate characters like `!` or `$`).*

```bash
sudo docker run -d \
  --name wuzapi \
  --restart unless-stopped \
  -p 8080:8080 \
  -e 'WUZAPI_ADMIN_TOKEN=7d8F2xKmQ9vN5zPwB4rT6sE1vC8aX9zB' \
  -e 'DB_DIALECT=sqlite' \
  -e 'WUZAPI_GLOBAL_ENCRYPTION_KEY=e2a4b8c1d7f03e5a6b9c2d4e8f1a3b5c' \
  -e 'WUZAPI_GLOBAL_HMAC_KEY=9f1b3d5e7c0a2f4b6e8d0c2a4f6b8e0d' \
  -e 'TZ=Asia/Karachi' \
  -v wuzapi-data:/app/dbdata \
  asternic/wuzapi

```

* `--restart unless-stopped` → starts automatically after a reboot.
* `-e 'DB_DIALECT=sqlite'` → **CRITICAL** forces Wuzapi to successfully structure database tables on its initial boot sequence.
* `-v wuzapi-data:/app/dbdata` + the fixed keys → **saves the WhatsApp login**, so you don't re‑scan after a machine restart.

Check status: `sudo docker ps` (STATUS "Up …"). Verify logs: `sudo docker logs -f wuzapi`.

---

## 3. Create the LabDesk user (one time)

This provisions the secure isolated account inside Wuzapi for your daily LabDesk transactions. Run this command from your terminal (*`sudo` is not needed for curl commands, as it is just an API call*):

```bash
curl -X POST http://localhost:8080/admin/users \
  -H "Authorization: 7d8F2xKmQ9vN5zPwB4rT6sE1vC8aX9zB" \
  -H "Content-Type: application/json" \
  -d '{"name":"LabDesk","token":"LD-prod-9a2b4c6d8e0f1a3b5c7d","events":"Message,ReadReceipt"}'

```

Keep your production **Access token** safe: **`LD-prod-9a2b4c6d8e0f1a3b5c7d`**

---

## 4. Link the lab's WhatsApp phone (scan the QR)

1. Open a browser and navigate to: **`http://localhost:8080/login`**
2. Paste your secure User Access Token: `LD-prod-9a2b4c6d8e0f1a3b5c7d`
3. A WhatsApp QR code will generate on your screen.
4. On the lab phone: **WhatsApp → Settings → Linked Devices → Link a Device → scan the QR code.**

It will link within a few seconds and show up under your active linked browser sessions.

---

## 5. Configure LabDesk

**Settings → WhatsApp gateway:**

| Field | Value |
| --- | --- |
| **Gateway URL** | `http://localhost:8080` *(use `https://…` if the gateway is on a remote machine)* |
| **Access token** | `LD-prod-9a2b4c6d8e0f1a3b5c7d` |
| **Country code** | `92` |
| **Auto‑send report (checkbox)** | tick to send the report automatically when results are saved |
| **Auto‑send bill (checkbox)** | tick to send the cash receipt automatically when a bill is saved |

Click **Save settings**, then click **Test connection** → it should reply: *"Gateway reachable — WhatsApp is linked and ready."*

> **Consent:** reports/bills are only sent to patients who have agreed. Each patient has a **"Send reports & bills on WhatsApp"** toggle in **Reception** (on by default, recorded with a timestamp). Untick it and nothing is sent to that patient.

---

## 6. Send a report

* **Manual:** Worklist/Results → open a receipt with results → **Send WhatsApp**.
* **Automatic:** if you ticked auto‑send, it goes out when results are saved.

The report PDF is sent to the patient's saved number (stored as `03XXXXXXXXX`; LabDesk converts it to `92XXXXXXXXXX` automatically).

---

## Everyday operations

| Task | Command / Action |
| --- | --- |
| **Is it running?** | `sudo docker ps` |
| **Logs / Debugging** | `sudo docker logs -f wuzapi` |
| **Restart container** | `sudo docker restart wuzapi` |
| **Phone unlinked?** | open `http://localhost:8080/login`, paste your user token, re‑scan |
| **Update wuzapi** | `sudo docker pull asternic/wuzapi && sudo docker rm -f wuzapi &&` *(re‑run step 2 using sudo)* |

---

## Troubleshooting

* **"Test connection" → token wrong / Unauthorized (401)**:
* Ensure the Access token in LabDesk exactly matches `LD-prod-9a2b4c6d8e0f1a3b5c7d`.
* If you are testing manually via `curl`, ensure you aren't missing the `Authorization:` header or cutting off special characters.


* **"WhatsApp isn't linked — scan the QR"**: Open `http://localhost:8080/login`, input your user token, and re-pair the phone.
* **Reports don't arrive**: Ensure the phone status shows **logged in**. Check that the patient's phone number uses valid formatting.
* **Logged out after a container update or system restart**: This happens if the environment variables changed, the `DB_DIALECT` flag was missed, or the `wuzapi-data` docker volume was deleted/purged. Ensure step 2 is followed precisely.
* **Gateway on another PC**: Set LabDesk's Gateway URL to that computer's IP address and expose port 8080. Prefer **`https://`** (e.g. running behind an Nginx reverse proxy) — otherwise, your access tokens and confidential patient PDFs travel across your local area network unencrypted. LabDesk **warns** before saving a plain‑`http` URL that points anywhere other than `localhost`.

---

## Notes

* wuzapi is free/open‑source (MIT) and perfectly lightweight for individual lab execution.
* Never expose port `8080` directly to the open internet without an explicit firewall rule; your user token is your perimeter defense.
* **Privacy:** delivery goes through WhatsApp (Meta), so reports/bills transit a third party. Send only to consenting patients (the per‑patient toggle in Reception) and cover WhatsApp delivery in your privacy policy.
* **Token storage:** the access token is kept in a private `0600` permissions file at `~/.local/share/LabDesk/.secrets.json` — never in the database or its backups, and never logged.
* `app/src/labdesk/whatsapp.py` is the only code that talks to the gateway — it posts to `/chat/send/document` with the `token` header, refuses cross‑host redirects, and confirms delivery from the gateway's JSON reply.
