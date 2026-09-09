# Deployment Guide

The app is a **single service**: FastAPI serves both the API and the static
front end. You deploy one thing. Below are four options, easiest first.

Everywhere you deploy, set these environment variables:

| Variable | Required | Example |
|----------|----------|---------|
| `GEMINI_API_KEY` | ✅ | `AIza...` (free from https://aistudio.google.com/app/apikey) |
| `GEMINI_CHAT_MODEL` | optional | `gemini-2.0-flash` |
| `GEMINI_EMBED_MODEL` | optional | `text-embedding-004` |
| `DATABASE_PATH` | optional | path on a persistent disk, e.g. `/var/data/knowledge.db` |
| `CORS_ORIGINS` | optional | `*` |

> **Persistence note:** the SQLite DB stores your uploaded documents and their
> embeddings. On platforms with an ephemeral filesystem, point `DATABASE_PATH`
> at a mounted disk (shown below) or your documents will need re-uploading after
> a redeploy.

---

## Option 1 — Render (recommended, has a free tier)

1. Push this project to a GitHub repository.
2. In Render, click **New + → Blueprint**.
3. Select your repo. Render detects `render.yaml`, which already defines:
   - a Python web service (`uvicorn backend.main:app`)
   - a 1 GB persistent disk mounted at `/var/data`
   - `DATABASE_PATH=/var/data/knowledge.db`
4. When prompted, add the secret **`GEMINI_API_KEY`**.
5. Click **Apply**. First build takes ~2–3 minutes.
6. Your app is live at `https://<your-app>.onrender.com`.
7. (Optional) Seed sample docs: open Render's **Shell** for the service and run
   `python seed.py`, or just upload documents from the UI.

## Option 2 — Railway

1. Push to GitHub, then in Railway: **New Project → Deploy from GitHub repo**.
2. Railway auto-detects Python. Set the start command if needed:
   `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
3. Add a **Variable** `GEMINI_API_KEY`.
4. Add a **Volume** and set `DATABASE_PATH` to a path inside it (e.g.
   `/data/knowledge.db`) for persistence.
5. Deploy — Railway gives you a public URL under **Settings → Networking**.

## Option 3 — Docker (any host / your own VM)

```bash
docker build -t enterprise-gpt .
docker run -d -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  -v $(pwd)/data:/app/data \
  --name enterprise-gpt enterprise-gpt
```

The `-v` mount keeps the SQLite DB (and thus your indexed documents) on the host.
Open http://localhost:8000. Put it behind Nginx/Caddy for HTTPS in production.

## Option 4 — Fly.io

```bash
fly launch --no-deploy          # generates fly.toml from the Dockerfile
fly volumes create data --size 1
# in fly.toml, mount the volume at /app/data and set DATABASE_PATH=/app/data/knowledge.db
fly secrets set GEMINI_API_KEY=your_key
fly deploy
```

---

## After deploying — smoke test

```bash
curl https://<your-app>/api/health
# -> {"status":"ok","llm_configured":true, ...}
```

Then open the URL in a browser, go to **Knowledge base → Upload document**, add a
file, switch to **Ask a question**, and query it. Add your live URL to the top of
`README.md`.

## Recording the demo video
Suggested flow (matches the brief's demo criteria):
1. Show the empty knowledge base, then upload a document (watch it index).
2. Ask a question answered **from the document** — show the citations + source cards.
3. Ask something the docs don't cover in **Hybrid** — show the "general knowledge" label.
4. Switch to **Ask anything** and ask a general question (the "answers like Google" part).
5. Open **Usage & quality** to show metrics, feedback and repeated-question detection.
Upload to Google Drive with "Anyone with the link can view".
