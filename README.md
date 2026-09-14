# CircuitLoop

Urbeno’s field collection app for certified e-waste pickup. Crews sign in on a phone, run today’s jobs, check in with GPS, log devices, apply tamper seals, take photos, capture a client signature, and close the chain of custody.

The field UI is the source of truth for the API. Nothing extra is exposed.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 43180 --reload
```

Open [http://127.0.0.1:43180](http://127.0.0.1:43180).

Demo crews (PIN **4821**): Priya Nair, Arjun Mehta, Sana Rahman.

Optional: `cp .env.example .env` and export those variables. The process starts with compiled local fallbacks if you skip this.

```bash
pytest -q
```

## Docker

```bash
docker build -t circuitloop .
docker run --rm -p 43180:8080 -e PORT=8080 circuitloop
```

## Deploy on Railway (Git)

1. Push this repo to GitHub or Origin.
2. In Railway: **New project → Deploy from GitHub repo** (or the Origin Git URL).
3. Railway builds the `Dockerfile`. A `Procfile` is there if Nixpacks is used instead.
4. Variables (all optional on first boot):

| Variable | What it does | Local fallback |
| --- | --- | --- |
| `PORT` | HTTP port | Railway injects; local `43180` |
| `DATA_DIR` | SQLite + photos | `/data` in Docker, `./data` locally |
| `SESSION_SECRET` | Signs the crew cookie | dev-only string |
| `CREW_PIN` | Shared field PIN | `4821` |
| `CORS_ORIGINS` | Allowed origins | `*` |

5. Add a volume mounted at `/data` and set `DATA_DIR=/data` so jobs survive restarts.
6. Health check path: `/api/health`.

No Railway token is required to develop or to push Git.

## What this slice does

- Crew session (cookie + PIN)
- Today / Done job board
- Start route, GPS check-in (or reason if GPS is denied)
- Asset log, seals, photos, canvas sign-off, complete with short-count override
- Seeded Bengaluru jobs so the board is not empty on first boot

## Not in this slice

- Offline CRDT sync (failed POSTs surface an error; retry from the UI)
- Postgres / `DATABASE_URL`
- Certificate PDFs and Urb TecTrack push
- Dispatcher console or per-crew PINs beyond the shared env PIN

## Layout

```
app/          FastAPI app, SQLite, crew session
static/       CircuitLoop field UI (Urbeno tokens)
data/         created at runtime (gitignored)
```
