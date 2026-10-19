# AI Trader — Agent Guide

Instructions for AI coding agents working in this repo. Human-facing overview: `README.md`.

## Source of truth

- `ARCHITECTURE.md` — system design, data flow, module map (繁體中文)
- `DECISIONS.md` — decision records with rationale (繁體中文)
- `PLAN.md` — current status and roadmap (繁體中文)

Keep these updated after architectural changes. Write them in 繁體中文, keeping technical terms in English.

## Layout

- `api/` — FastAPI backend (Python 3.13). Entry: `api/api/main.py`. Scheduler: `api/api/trading/scheduler.py`.
- `web/` — Next.js 16 dashboard. Read `web/AGENTS.md` before writing Next.js code.

## Commands

```bash
cd api && python -m pytest -q                  # backend tests
cd web && npx tsc --noEmit && npm run build    # frontend checks
```

## Rules

- **Live experiment.** Season 3 is running on Fly.io with persistent state. Deploy only when asked, and only outside market hours where possible (US 9:30–16:00 ET, TW 9:00–13:30 Asia/Taipei).
- **Season data.** Queries must filter by `season`. Seasons 1–2 are archived baselines.
- **No risk guardrails by design.** Agents are fully autonomous on paper money. If real money is ever discussed, risk controls must be restored first (`risk_rules.py` lives in git history; see `DECISIONS.md`).
- **Control endpoints are admin-only.** `POST /api/start|stop|cycle|cycle/tw` require `X-Admin-Token` (`ADMIN_TOKEN` env/Fly secret). Never expose the token to the frontend.
- **Costs are always on.** Use `ZERO_COST_MODEL` only in tests.
- **Secrets.** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `ADMIN_TOKEN` come from env / `fly secrets`. Never commit them. The production DB is never committed.
- **LLM model IDs and pricing.** Verify against the official provider docs before changing `api/api/llm/models.py`.
- **Structured outputs, not forced tools.** Current Claude models reject forced `tool_choice`; decisions use `output_config.format` (JSON schema adapted by `_strict_schema_anthropic`). Thinking/reasoning tokens count toward `max_tokens` and bill as output.
