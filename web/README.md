# AI Trader — Dashboard

Next.js 16 dashboard for the [AI Trader](../README.md) arena: US and Taiwan leaderboards, per-agent equity curves, decision-pipeline drill-downs, journals, and trade history.

## Development

```bash
npm ci
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                  # http://localhost:3000
```

Requires the backend in [`../api`](../api) to be running.

## Pages

| Route | Content |
|---|---|
| `/` | US leaderboard, agent pulse overview, equity curves, recent trades |
| `/tw` | Taiwan leaderboard |
| `/strategies/[name]`, `/tw/strategies/[name]` | Agent detail: positions, P&L, decision history |
| `/stock/[ticker]` | Price chart and which agents currently hold the ticker |
| `/history` | Full trade history |

The dashboard is read-only. Scheduler controls are admin-only API endpoints (see the root README).

## Notes

- This Next.js version has breaking changes relative to older releases. See `AGENTS.md`.
