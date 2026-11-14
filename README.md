# LexiScan: human-in-the-loop contract review

LexiScan reviews contracts from **your** side of the deal, checks them against **your** playbook, and
stops for your judgement at every point that matters. The AI drafts and you decide. Every
correction you make becomes a visible, editable preference that shapes the next draft.

- **client/**: React 19 + TypeScript + Vite (light, dark and system themes)
- **server/**: FastAPI + LangGraph (SQLite checkpointer) + Groq (free tier) via the Groq SDK

## Quickstart

```bash
# Backend
cd server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GROQ_API_KEY=gsk_...             # free at console.groq.com; without it, offline mode
uvicorn main:app --reload --port 5001

# Frontend
cd client
cp .env.example .env
npm install
npm run dev                              # http://localhost:5173
```

Click a sample contract on the Contracts page to try the full flow in under a minute.

**Offline mode.** With no API key, every graph node falls back to deterministic heuristics: pattern-based
risk flags, extractive answers, and regex obligations. The workflow, gates, learning and audit trail
behave identically, and the UI labels which engine produced each step. If an individual model call
fails (rate limit, outage), only that step falls back, and the step is labelled `offline-fallback`.

## Architecture

Two LangGraph state machines, both checkpointed to SQLite so a paused run survives restarts and can be
resumed days later.

### Contract review graph

```
prepare ─┬─► analyze_clauses ─► check_playbook ─┐
         └─► extract_obligations ───────────────┴─► score ─► human_triage ⏸
                                                                  │
                         finalize ◄─ approve/edit ─ memo_review ⏸ ◄─ draft_memo ◄─ learn
                                                        └── revise ──► draft_memo
```

- **Parallel fan-out**: obligations run alongside clause analysis; the playbook check uses the analysis.
- **`human_triage` interrupt**: every finding is accepted, edited, dismissed or escalated. Medium and
  high findings block submission. Dismissing a high-risk finding requires a reason.
- **`learn`**: dismissals and edited redlines become reviewer preferences for future reviews.
- **`memo_review` interrupt**: approve, edit directly, or send back with feedback (bounded loop).

### Q&A graph

```
plan ─► clarify ⏸ ─► plan            (only if the question is ambiguous)
  └──► retrieve ─► draft ─► verify ─(bad quotes: retry once)─► draft
                              └─► gate ─(policy allows)─► finalize
                                    └─► human_review ⏸ ─ approve / edit / reject ─► finalize
                                                 └── revise (+ feedback, pinned/excluded clauses) ─► retrieve
```

- **Clarification interrupt**: the assistant asks instead of guessing.
- **Deterministic citation verification**: every claim must carry verbatim quotes; `verify` matches them
  against the source text (exact, then fuzzy) with no model involved. Unverified quotes are shown in red
  and always force human review.
- **Policy gate (autonomy dial)**: `always` / `smart` (confidence threshold, verification, question type)
  / `never`, with a **safety floor**: unverifiable quotes or answers that depend on outside law always go
  to a human, whatever the policy.
- **Evidence steering**: when requesting a revision, the reviewer can pin or exclude clauses.
- **Learning from edits**: an edited or rejected answer is distilled into a one-line lesson
  (`CorrectionLesson`), stored as a reviewer preference and applied to later drafts.
- **Time travel**: `GET /threads/{id}/history` lists checkpoints; `POST /threads/{id}/rewind` forks from
  any of them, optionally with a new question or new pins.

### Model usage (`server/app/llm.py`)

- Groq, model `openai/gpt-oss-120b` by default (override with `GROQ_MODEL`), with per-node reasoning effort.
- Strict JSON-schema structured outputs generated from the Pydantic schemas in `schemas.py`; if a strict
  call is rejected it retries once in JSON mode, and every response is validated with Pydantic.
- Calls run one at a time (`LEXISCAN_LLM_CONCURRENCY`) and rate limits are retried with back-off, to
  stay inside Groq's free-tier tokens-per-minute limits.
- Any failure (bad key, rate limit, malformed output) falls back to the offline heuristics for that step,
  and the step is labelled `offline-fallback` so the reviewer knows.

### User-specific features

| Feature | Where |
| --- | --- |
| Perspective (which party you represent) | Set per contract before review |
| Playbook rules + presets (SaaS buyer, vendor, employee, NDA) | `/app/playbook` |
| Learned preferences: view, edit, pause, delete, add | `/app/memory` |
| Review policy, confidence threshold, expertise level, jurisdiction | `/app/settings` |
| PII redaction before model calls (reversible, per-document tokens) | `/app/settings` |
| Obligations per party, due dates, calendar export (.ics with 7-day reminders) | Obligations tab |
| Audit trail of every AI action and human decision, CSV export | `/app/audit` |
| Defined-term hover cards, clause risk markers, quote highlighting | Document viewer |
| Keyboard triage (`j`/`k`, `a`, `e`, `d`, `x`, `u`) | Review tab |

Users are identified by an `X-User-Id` header generated per browser. Put real authentication in front of
the API before multi-user deployment.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | — | Enables the model (free key from console.groq.com); without it, offline mode |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq model id |
| `LEXISCAN_LLM_CONCURRENCY` | `1` | Parallel model calls (raise on a paid Groq tier) |
| `LEXISCAN_EFFORT` | `medium` | Default effort; some nodes override it |
| `LEXISCAN_OFFLINE` | — | `1` forces offline mode |
| `LEXISCAN_DATA_DIR` | `server/var` | SQLite app DB and checkpoints |
| `LEXISCAN_CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `LEXISCAN_MAX_REVISIONS` | `4` | Revision loop bound |
| `VITE_BACKEND_URL` (client) | dev: `http://127.0.0.1:5001`, prod build: `https://lexiscan-backend-gupj.onrender.com` | API base URL |

Run one server worker: checkpoints and per-thread run locks are process-local SQLite.

## Deploy

**Backend on Render** (Python service, root directory `server`):

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1`
  (the legacy `gunicorn app:app` command also works; `gunicorn.conf.py` selects the uvicorn worker)
- Python version comes from `server/.python-version` (3.12)
- Environment variables: `GROQ_API_KEY` (otherwise offline mode); optionally `LEXISCAN_CORS_ORIGINS=https://<your-app>.vercel.app`
- Free instances have an ephemeral disk, so the SQLite data resets on redeploys and restarts. To keep it, attach a
  persistent disk and set `LEXISCAN_DATA_DIR` to the mount path.

**Frontend on Vercel** (root directory `client`, Vite preset): set `VITE_BACKEND_URL` to the Render URL
if it differs from the default above. `vercel.json` rewrites every route to `index.html` so deep links work.

## Tests

```bash
cd server && pip install pytest httpx && pytest -q
```

The end-to-end suite runs both graphs offline through the HTTP API: interrupts, triage rules, memo
revision, clarification, revise with pins and exclusions, edit-and-learn, rewind and fork, the policy
safety floor, ICS export and the audit trail.

## Disclaimer

LexiScan assists qualified reviewers. It is not legal advice.
