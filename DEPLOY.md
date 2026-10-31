# Deploying Proctor

The MVP is a single FastAPI app (dashboard + REST API). It binds to **localhost by default** —
before putting it on a network you **must** set `PROCTOR_API_KEY` so `/api` is protected (docs/06).

## Required / useful env vars

| Var | Purpose |
|---|---|
| `OPENAI_API_KEY` | Enables real persona generation, judging, and the demo bot. Omit → deterministic offline mode. |
| `PROCTOR_API_KEY` | **Set this when public.** Requires `X-API-Key` on every `/api` route except health. |
| `PROCTOR_HOST` | `0.0.0.0` in a container (set automatically in the Dockerfile). |
| `PORT` / `PROCTOR_PORT` | Port to bind. Cloud hosts inject `PORT`; otherwise 8080. |
| `PROCTOR_DB` | SQLite path. Point at a mounted volume to persist runs. |
| `PROCTOR_MODE` | `auto` (default), `offline`, or `live`. |

## Option A — Docker (anywhere)

```bash
docker build -t proctor .
docker run -p 8080:8080 \
  -e OPENAI_API_KEY=sk-... \
  -e PROCTOR_API_KEY=choose-a-long-random-string \
  -v proctor_data:/data \
  proctor
# → http://localhost:8080
```

## Option B — Render (one click)

This repo ships a [`render.yaml`](render.yaml). On https://render.com choose **New → Blueprint**,
point it at this repo, then set `OPENAI_API_KEY` and `PROCTOR_API_KEY` as secrets in the dashboard.
Health check is `/api/health`; a 1 GB disk is mounted at `/data` for the SQLite DB.

## Option C — Fly.io / Cloud Run / Railway

Any platform that builds a Dockerfile works. They inject `$PORT` (honored by `config.py`). Mount a
volume at `/data` for persistence and set the env vars above.

## Before a real/public launch

- Set `PROCTOR_API_KEY` (and put the app behind HTTPS — every host above terminates TLS for you).
- Keep `PROCTOR_DEV_ECHO_CODE` **off** (default) so ownership codes are never returned by the API.
- Remember the voice channel still needs the Twilio + Realtime pipeline wired in (see README).
- This MVP is single-tenant; full multi-tenant auth/isolation is a platform milestone (docs/02, docs/06).
