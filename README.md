# CircuitLoop

Urbeno field console for IT asset testing and project management. The UI is the original CircuitLoop Field HTML; FastAPI persists that in-memory `DB` and proxies Blancco lookups.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 43180 --reload
```

Open [http://127.0.0.1:43180](http://127.0.0.1:43180).

Sign in by picking a demo user. Super Admin (Manish Kumar, S. Iyer) sees every module. Field Engineers see Scan & Test and My Projects for assigned work.

Optional: `cp .env.example .env`. The process starts with compiled local fallbacks if you skip this.

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
| `DATA_DIR` | JSON state file | `/data` in Docker, `./data` locally |
| `SESSION_SECRET` | Signs the user cookie | dev-only string |
| `BLANCCO_API_KEY` | Live Blancco Management Console | empty → demo simulation |
| `CORS_ORIGINS` | Allowed origins | `*` |

5. Add a volume mounted at `/data` and set `DATA_DIR=/data` so the asset register survives restarts.
6. Health check path: `/api/health`.

No Railway token is required to develop or to push Git.

## What this slice does

- Serves CircuitLoop Field (Urbeno wordmark, Scan & Test, projects, register, Blancco, reconciliation, reports, masters, users)
- `GET`/`PUT /api/state` persists the UI `DB`
- Click-to-sign-in session cookie
- Blancco live lookup via the server (demo simulation if no key)

## Not in this slice

- Pickup GPS / seals / signature workflow (not in the field HTML)
- Postgres
- Real Blancco reports when Live mode has no reachable API (falls back to simulation)

## Layout

```
app/          FastAPI app, JSON store, session, Blancco proxy
static/       circuitloop-field.html (+ persist.js)
data/         created at runtime (gitignored)
```
