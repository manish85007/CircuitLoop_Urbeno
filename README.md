# CircuitLoop

Field console for IT asset testing and project management. The UI is CircuitLoop Field; FastAPI persists that in-memory `DB` and proxies Blancco lookups.

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
3. Railway builds the `Dockerfile`. Start command is `python -m app`, which binds to Railway's `PORT` without shell expansion. A `Procfile` is there if Nixpacks is used instead.
4. Variables (all optional on first boot):

| Variable | What it does | Local fallback |
| --- | --- | --- |
| `PORT` | HTTP port | Railway injects; local `43180` |
| `DATA_DIR` | JSON state file | `/data` in Docker, `./data` locally |
| `BACKUP_DIR` | Latest snapshot only | `$DATA_DIR/backups` |
| `BACKUP_HOUR_UTC` / `BACKUP_MINUTE_UTC` | Daily backup clock | `18` / `30` (00:00 IST) |
| `SESSION_SECRET` | Signs the user cookie | dev-only string |
| `BLANCCO_API_KEY` | Live Blancco Management Console | empty → demo simulation |
| `CORS_ORIGINS` | Allowed origins | `*` |

5. Production mounts a volume at `/data` with `DATA_DIR=/data` so the asset register survives restarts.
6. Health check path: `/api/health` (includes last backup).
7. Daily backup runs **in-process** on `web` (same volume, no extra Railway service).

No Railway token is required to develop or to push Git.

## Backups (production)

The live register stays at `/data/circuitloop-state.json`. Backups are a second copy on the **same** `/data` volume. The job never deletes or rewrites the live file.

| | |
| --- | --- |
| Schedule | Daily at **18:30 UTC** (00:00 IST). Also one catch-up ~20s after process start if there is no backup yet, or the latest is older than 20 hours (so a deploy still creates a copy). |
| Location | `/data/backups/circuitloop-<UTC stamp>/` (stamp includes microseconds) |
| Contents | `circuitloop-state.json` (the Field register) plus any other files in `/data` except `backups/` and `*.tmp`. `manifest.json` records rev, size, and sha256. |
| Rotation | After a **successful** new backup, every previous directory under `/data/backups/` is deleted. **Only the latest backup remains.** If a backup fails, the previous backup is kept and live data is left alone. |
| Status | `GET https://loop.urbeno.in/api/health` → `backup.latest` |

Disable with `BACKUP_ENABLED=0`. Override the clock with `BACKUP_HOUR_UTC` / `BACKUP_MINUTE_UTC`.

```bash
python -m app.backup status   # latest backup
python -m app.backup run      # take a new copy now (then delete the previous one)
```

### Restore

This overwrites the live register with the latest backup. Do it only when you intend to roll back. Use a Railway shell / one-off on service `web` so `/data` is mounted (`DATA_DIR=/data`).

```bash
python -m app.backup status    # confirm backup.latest
python -m app.backup restore   # atomic replace of /data/circuitloop-state.json
```

Or copy by hand:

```bash
cp /data/backups/circuitloop-<stamp>/circuitloop-state.json /data/circuitloop-state.json
```

The API reads the file on each request, so a restart is optional. Hard-refresh the Field UI so it pulls the restored `_rev`.

Do **not** delete `/data/circuitloop-state.json` first. Restore replaces it in place. The backup directory is not deleted by restore.

## What this slice does

- Serves CircuitLoop Field (CircuitLoop lockup, Scan & Test, projects, register, Blancco, reconciliation, reports, masters, users)
- `GET`/`PUT /api/state` persists the UI `DB`
- Daily backup of `/data` on the same volume (keep latest only); restore via `python -m app.backup restore`
- Click-to-sign-in session cookie
- Blancco live lookup via the server (demo simulation if no key)

## Not in this slice

- Pickup GPS / seals / signature workflow (not in the field HTML)
- Postgres
- Real Blancco reports when Live mode has no reachable API (falls back to simulation)

## Layout

```
app/          FastAPI app, JSON store, daily backup, session, Blancco proxy
static/       circuitloop-field.html (+ persist.js)
data/         created at runtime (gitignored); production is the Railway volume at /data
data/backups/ latest snapshot only (runtime)
```
