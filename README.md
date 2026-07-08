# AI Trader

AI-powered stock trading system with quant signals, LLM-assisted decisions, and paper trading portfolio management.

## Structure

- **`api/`** — Python FastAPI backend (deployed on Fly.io as `ai-trader-api`)
  - `api/quant/` — quant modules: factors, signals, regime detection, ML combiner, portfolio optimizer, risk rules, anomaly/earnings/insider analysis
  - `api/trading/` — portfolio management, strategies (US + TW), scheduler
  - `api/llm/` — LLM client (Anthropic / OpenAI)
  - `api/data/` — market data & news fetching
  - `api/routes/` — API endpoints (decision, trading, portfolio, performance, health)
  - `tests/` — test suite
- **`web/`** — Next.js frontend (deployed on Fly.io as `ai-trader-web`)
  - ⚠️ **Source code not yet recovered** — the deployed Fly image only contains the compiled
    `.next` standalone build (no sourcemaps with original content). The original source lives
    on another PC and needs to be added to this repo. Recovered so far: `package.json`
    (dependency list) and `public/` assets.
  - Pages in the deployed app: `/`, `/history`, `/settings`, `/strategies/[name]`, `/tw`, `/tw/strategies/[name]`

## Deployment

- API: `ai-trader-api.fly.dev` — Fly.io, `sjc` region, 1GB volume mounted at `/data` (SQLite `trading.db`)
- Web: `ai-trader-web.fly.dev` — Fly.io, 2 machines in `sjc`

## Environment variables (API)

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`

Set via `fly secrets set` — never commit keys to this repo.

## Data backup

The live SQLite database (`/data/trading.db` on the API machine — trades, snapshots,
decision log) is backed up separately and is **not** stored in this repo.

## Recovery note

This repo was reconstructed on 2026-07-08 by extracting code from the running Fly.io
machines (`fly ssh console` + `fly ssh sftp`), since the original source was not in
version control.
