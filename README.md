# CircuitLoop

Field console for IT asset testing. FastAPI persists a JSON register, enforces login, and proxies Blancco lookups.

Production: https://loop.urbeno.in

## Sign in (production)

Login is restricted to:

| Email | Role |
| --- | --- |
| **manish@urbeno.in** | Super Admin |
| **darshak@urbeno.in** | User / Field Engineer |

Roles are assigned on the server. There is no click-a-name login.

### First-time authenticator (TOTP) enroll

SMTP is optional. If no email API is configured, authenticator is the working factor.

1. Open https://loop.urbeno.in
2. Enter your Urbeno email and **Continue with authenticator**.
3. Add **CircuitLoop** in Google Authenticator, Authy, or 1Password:
   - Scan the QR code, or copy the secret / `otpauth://` URL.
   - Keep a single CircuitLoop entry. Each extra entry from an earlier try will not match.
4. Enter the 6-digit code to confirm. That binds the authenticator to your account.
5. After a successful code, Field must show the sidebar modules (Dashboard, Scan & Test, Projects, Asset Register, …) and Sign out must return to the email card. Hard-refresh once after a deploy so `persist.js?v=prod6` loads.

If a code does not match, use **Set up a new authenticator QR**, delete the old CircuitLoop entry in the app, and scan the new code. The previous secret stays valid until the new one is confirmed.

If `BOOTSTRAP_TOKEN` is set on the server, the first enroll also requires that token (recommended).

### Email OTP (optional)

When SMTP is configured, Continue emails a 6-digit code (10 minutes). You can still use TOTP if enrolled.

| Variable | Purpose |
| --- | --- |
| `SMTP_HOST` | Enable email OTP (unset = TOTP only) |
| `SMTP_PORT` | Default `587` |
| `SMTP_USER` / `SMTP_PASSWORD` | SMTP auth |
| `SMTP_FROM` | From address |
| `SMTP_STARTTLS` | Default on |

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
| `BOOTSTRAP_TOKEN` | Optional extra check for first TOTP enroll |
| `BLANCCO_API_KEY` | Live Blancco only. **Not stored in the register.** |
| `BLANCCO_ENDPOINT` | Blancco API URL |
| `CORS_ORIGINS` | Default `https://loop.urbeno.in` |
| `BACKUP_KEEP_DAILY` / `BACKUP_KEEP_MONTHLY` | Default 30 / 12 |
| SMTP_* | Email OTP |

On first boot of this version the historical register (demo users, assets, clients, projects, simulated Blancco) is wiped to an empty production register containing only the two users. A cutover marker on `/data` prevents a second wipe.

## Backups

Daily at 18:30 UTC plus catch-up after start. Keeps **30 daily** and **12 monthly** copies on `/data/backups`. Restore:

```bash
python -m app.backup status
python -m app.backup restore
```

Health (`GET /api/health`) reports backup policy without filesystem paths.

## API

Session cookie required on every `/api/*` except `/api/health`, `/api/auth/start`, `/api/auth/verify` (and `/api/otp`). `/docs`, `/redoc`, `/openapi.json` are off.

Per-record writes: `POST/PUT /api/assets`, `/api/clients`, `/api/projects`, `/api/company`, `/api/config`, `/api/sync`. Whole-DB `PUT /api/state` is disabled.

Field Engineers only receive assigned projects/assets. Super Admin sees the full register minus secrets.

## Not in this slice

- Pickup GPS / seals / signature workflow
- Postgres
- Live Blancco reports when `BLANCCO_API_KEY` is unset (lookups fail rather than simulating)
