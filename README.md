# CircuitLoop

Field console for IT asset testing. FastAPI persists a JSON register, enforces login, and proxies Blancco lookups.

Production: https://loop.urbeno.in

## Sign in (production)

Built-in accounts:

| Email | Role |
| --- | --- |
| **manish@urbeno.in** | Super Admin |
| **darshak@urbeno.in** | Field Engineer (Super Admin can change this to Lead Engineer) |

Three access levels:

| Role | What they can do |
| --- | --- |
| **Super Admin** | Everything: Users, Masters, Blancco config, reconciliation, verify |
| **Lead Engineer** | Create clients/projects, assign Field Engineers, verify and reopen captures. Not Users/Masters/Blancco config |
| **Field Engineer** | Dashboard, Scan & Test, My Projects for assigned work only |

A Super Admin can add more people from **Users → Add user** and change an existing person’s access level. New accounts cannot self-enroll from the login page. The Super Admin sends an authenticator invite (Users → Send invite, or the token shown when adding the user). Roles are assigned on the server. There is no click-a-name login and no password store.

### First-time authenticator (TOTP) enroll

SMTP is optional. If no email API is configured, authenticator is the working factor after enroll.

1. Super Admin signs in, then **Users → Add user** (or **Send invite** on an existing person who has never enrolled).
2. Copy the invite link (token is shown once). The person opens that link on a trusted device.
3. They add **CircuitLoop** in Google Authenticator, Authy, or 1Password (scan the QR, or type the secret).
4. They enter the 6-digit code to bind the authenticator.
5. Later visits: email + current 6-digit authenticator code. There is no public **Set up a new authenticator QR** on the login card.

To replace an authenticator you still have: Sign in → **Replace authenticator** and enter the current 6-digit code, then scan the new QR.

If the authenticator is lost: Super Admin → **Reset authenticator** on that user, then send the new invite. The previous code stops working immediately.

`BOOTSTRAP_TOKEN` is no longer the enroll gate. First-time TOTP is invite-only.

### Email OTP

Production on GCE (`loop.urbeno.in`) can send Gmail SMTP. Railway Hobby/Trial still **blocks outbound SMTP** (ports 25, 465, 587) if you hit that host — Gmail there will 503. Prefer **Resend/SendGrid/Mailgun HTTPS** on Railway. Authenticator still works.

Set these on the Railway **web** service (not a worker):

| Variable | Purpose |
| --- | --- |
| `RESEND_API_KEY` | HTTPS email via [Resend](https://resend.com) — works on Hobby |
| `SENDGRID_API_KEY` | HTTPS email via SendGrid |
| `MAILGUN_API_KEY` + `MAILGUN_DOMAIN` | HTTPS email via Mailgun |
| `SMTP_FROM` | From address (must be allowed by the HTTPS provider) |
| `SMTP_HOST` | SMTP server (Gmail: `smtp.gmail.com`) — **Pro plan + redeploy only** |
| `SMTP_PORT` | Default `587` (app also tries `465` SSL) |
| `SMTP_USER` / `SMTP_PASSWORD` | SMTP auth (Gmail app password) |
| `SMTP_STARTTLS` | Default on for 587 |

Local Preview with `PREVIEW_LOGIN=1` shows the code on screen when mail cannot be sent. Production never returns the code in the API.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 43180 --reload
```

Open [http://127.0.0.1:43180](http://127.0.0.1:43180). Sign in as above. The local register starts empty except the two users.

For a local Preview that opens Field as Super Admin (never on Railway):

```bash
PREVIEW_LOGIN=1 COOKIE_SECURE=0 uvicorn app.main:app --host 127.0.0.1 --port 43180
```

```bash
pytest -q
```

## Deploy on Railway (Git)

Push to `main`. Service `web` builds the Dockerfile. Volume at `/data`.

| Variable | What it does |
| --- | --- |
| `PORT` | Railway injects |
| `DATA_DIR` | `/data` |
| `SESSION_SECRET` | Cookie signing — set a long random string |
| `COOKIE_SECURE` | Auto-on for `/data`; keep on in production |
| `BOOTSTRAP_TOKEN` | Unused for enroll (invite-only). Safe to leave empty. |
| `BLANCCO_API_KEY` | Live Blancco only. **Not stored in the register.** |
| `BLANCCO_ENDPOINT` | Blancco API URL |
| `CORS_ORIGINS` | Default `https://loop.urbeno.in` |
| `BACKUP_KEEP_DAILY` / `BACKUP_KEEP_MONTHLY` | Default 30 / 12 |
| SMTP_* | Email OTP over SMTP (often blocked on Railway) |
| `RESEND_API_KEY` | Email OTP over HTTPS (recommended on Railway) |

On first boot of this version the historical register (demo users, assets, clients, projects, simulated Blancco) is wiped to an empty production register containing only the two users. A cutover marker on `/data` prevents a second wipe.

## Backups

Daily at 18:30 UTC plus catch-up after start. Keeps **30 daily** and **12 monthly** copies on `/data/backups`. Restore:

```bash
python -m app.backup status
python -m app.backup restore
```

Health (`GET /api/health`) reports backup policy without filesystem paths.

## API

Session cookie required on every `/api/*` except `/api/health`, `/api/auth/start`, `/api/auth/verify`, `/api/auth/rotate` (and `/api/otp`). `/docs`, `/redoc`, `/openapi.json` are off. Unauthenticated start never returns a TOTP secret. First enroll is `inviteToken` from a Super Admin. Rotate requires the current 6-digit code.

Per-record writes: `POST/PUT /api/assets`, `/api/clients`, `/api/projects`, `/api/company`, `/api/config`, `/api/sync`. Whole-DB `PUT /api/state` is disabled.

Field Engineers only receive assigned projects/assets. Lead Engineers and Super Admins see the full register minus secrets. Users, Masters, company, and Blancco config stay Super Admin only.

## Not in this slice

- Pickup GPS / seals / signature workflow
- Postgres
- Live Blancco reports when `BLANCCO_API_KEY` is unset (lookups fail rather than simulating)
