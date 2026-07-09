# AI Trader — Project Documentation

> ⚠️ 本文件是從舊 PC 救回的原始文檔，部分內容已過時。**現況以 `ARCHITECTURE.md` /
> `PLAN.md` / `DECISIONS.md` 為準**。已知過時處：risk rules 已拆除（Phase 3 Soul
> Agents，agent 完全自主）、scheduler 已改 event-driven tick、model 已升級
> claude-opus-4-8 / claude-sonnet-5、目錄 backend/ → api/、frontend/ → web/。

## What This Is
AI 模擬交易競技場：10 個有靈魂的自主 AI trader 各拿 $10K (美股) / NT$300K (台股)，
自己決定何時交易、何時睡覺、要不要 all-in。賽季制，爆倉出局。

## Architecture

```
ai-trader/
├── backend/          Python FastAPI (port 8000)
│   ├── api/
│   │   ├── main.py           # FastAPI app, auto-starts scheduler on boot
│   │   ├── llm/
│   │   │   ├── client.py     # LLMClient: direct Anthropic + OpenAI SDK (NO LangChain)
│   │   │   └── models.py     # Model registry (claude-opus-4-6, claude-sonnet-4-6, gpt-5.4)
│   │   ├── trading/
│   │   │   ├── strategies.py    # 5 US strategies (Buffett, ARK, Momentum, Balanced, Quant)
│   │   │   ├── strategies_tw.py # 5 TW strategies (same types, Taiwan stocks)
│   │   │   ├── scheduler.py     # APScheduler: frequency-tiered (15min/30min/1hr)
│   │   │   ├── portfolio.py     # SimulatedPortfolio (cash + positions + trade history)
│   │   │   └── models.py        # Pydantic: TradeOrder, TradeDecision, Position, etc.
│   │   ├── quant/              # Quantitative engine (pure math, no LLM)
│   │   │   ├── signals.py     # Technical: RSI, MACD, Bollinger, SMA, ATR, scoring
│   │   │   ├── factors.py     # Factor model: Value, Momentum, Quality, Size, Volatility
│   │   │   ├── regime.py      # HMM market regime detection (bull/bear/crisis)
│   │   │   ├── insider.py     # SEC Form 4 insider trading signals
│   │   │   ├── ml_combiner.py # Combine all signals into ranked composite score
│   │   │   ├── portfolio_optimizer.py  # Score-weighted inverse-vol portfolio weights
│   │   │   ├── position_sizing.py     # Kelly Criterion + ATR stop loss
│   │   │   ├── risk_rules.py  # Hard risk rules (stop loss, max position, etc.)
│   │   │   ├── earnings.py    # Earnings news analysis
│   │   │   └── anomaly.py     # Anomaly detection (unusual signal combos)
│   │   ├── data/
│   │   │   ├── market.py     # yfinance: prices, RSI, SMA20, volume
│   │   │   └── news.py       # Google News RSS (free, no API key)
│   │   ├── db/
│   │   │   └── sqlite.py     # SQLite: trades, portfolio_states, snapshots, decision_log
│   │   └── routes/
│   │       ├── trading.py    # POST /api/cycle, GET /api/strategies, etc.
│   │       ├── portfolio.py  # GET /api/portfolios, /api/trades, /api/portfolios/{s}/positions
│   │       ├── performance.py # GET /api/performance (Sharpe, drawdown, win rate)
│   │       ├── decision.py   # GET /api/decision/{strategy} (full decision pipeline)
│   │       └── health.py     # GET /api/health
│   ├── requirements.txt
│   ├── Dockerfile
│   └── fly.toml              # Fly.io config (sjc region, 512MB, persistent volume)
│
├── frontend/         Next.js 16 + Tailwind + shadcn/ui (port 3000)
│   ├── app/
│   │   ├── page.tsx              # US Dashboard (leaderboard, chart, trades)
│   │   ├── strategies/[name]/    # US strategy detail (positions, P&L, charts)
│   │   ├── tw/page.tsx           # Taiwan Dashboard
│   │   ├── tw/strategies/[name]/ # TW strategy detail
│   │   ├── history/              # Full trade history
│   │   └── settings/             # Settings page
│   ├── components/
│   │   ├── leaderboard.tsx       # 5 strategy cards ranked by performance
│   │   ├── trade-feed.tsx        # Recent trades table
│   │   ├── status-bar.tsx        # Trading active/stopped controls
│   │   ├── strategy-card.tsx     # Portfolio positions table
│   │   ├── position-chart.tsx    # 30-day mini stock chart (recharts)
│   │   ├── market-nav.tsx        # US/TW market switcher
│   │   ├── market-banner.tsx     # Auto-detect open market banner
│   │   └── decision-flow.tsx     # 5-step decision pipeline visualization
│   ├── lib/
│   │   ├── api.ts                # API client (all US + TW endpoints)
│   │   └── utils.ts              # formatCurrency, formatPercent, etc.
│   ├── Dockerfile
│   └── fly.toml
│
└── CLAUDE.md (this file)
```

## Deployment
- **Backend**: https://ai-trader-api.fly.dev (Fly.io, sjc region, 1GB persistent volume)
- **Frontend**: https://ai-trader-web.fly.dev (Fly.io, sjc region)
- Deploys: `cd backend && fly deploy` / `cd frontend && fly deploy`
- Backend auto-starts trading scheduler on boot (no manual /api/start needed)
- **Auto-deploy rule**: After making any code changes, always run `fly deploy` for the affected service(s) automatically — do not wait for the user to ask.

## AI Models
- **Claude Opus 4.8** (`claude-opus-4-8`): Buffett strategies (US + TW)
- **Claude Sonnet 5** (`claude-sonnet-5`): ARK + Balanced strategies
- **GPT-5.4** (`gpt-5.4`): Momentum + Quant strategies
- Anthropic agents 有 research phase（web_search tool，max 3 searches/決策，$0.01/search）

## Trading Strategies

### US Market (9:30 AM - 4:00 PM ET)
| Strategy | Model | Frequency | Watchlist |
|----------|-------|-----------|-----------|
| 🧓 Buffett (Warren AI) | Claude Opus | 1 hour | 30 blue-chip value stocks |
| 🚀 ARK (Cathie AI) | Claude Sonnet | 30 min | FREE (any stock) |
| ⚡ Momentum Bot | GPT-5.4 | 15 min | FREE (any stock) |
| ⚖️ Balanced (Risk Parity) | Claude Sonnet | 30 min | 30 large+mid cap |
| 🤖 Quant Engine | GPT-5.4 | 15 min | 30 high-liquidity stocks |

### Taiwan Market (9:00 AM - 1:30 PM Taiwan time)
| Strategy | Model | Frequency | Watchlist |
|----------|-------|-----------|-----------|
| 🧓 巴菲特AI | Claude Opus | 1 hour | 30 台灣藍籌 (.TW suffix) |
| 🚀 女股神AI | Claude Sonnet | 30 min | FREE |
| ⚡ 動能機器人 | GPT-5.4 | 15 min | FREE |
| ⚖️ 風險平衡 | Claude Sonnet | 30 min | 30 台灣大中型 |
| 🤖 量化引擎 | GPT-5.4 | 15 min | 30 台灣高流動性 |

## Starting Capital
- US: $10,000 per strategy ($50K total)
- TW: NT$300,000 per strategy (NT$1.5M total)

## API Endpoints
```
# US
GET  /api/health
GET  /api/strategies
GET  /api/status
POST /api/cycle          # Manual trigger
POST /api/start
POST /api/stop
GET  /api/portfolios
GET  /api/portfolios/{strategy}
GET  /api/portfolios/{strategy}/positions  # With 30-day chart data
GET  /api/trades?strategy=X&market=us&limit=50
GET  /api/snapshots/{strategy}

# Taiwan
GET  /api/strategies/tw
POST /api/cycle/tw
GET  /api/portfolios/tw
GET  /api/portfolios/tw/{strategy}
GET  /api/portfolios/tw/{strategy}/positions
GET  /api/trades?market=tw

# Performance
GET  /api/performance            # All US strategy metrics
GET  /api/performance/tw         # All TW strategy metrics
GET  /api/performance/{strategy} # Single strategy (US or TW)

# Decision Flow (full pipeline transparency)
GET  /api/decision/{strategy}          # Latest decision pipeline data
GET  /api/decision/{strategy}/history  # Decision history (limit=10)
```

## Quant Engine Architecture (5 Layers)
```
Layer 0: DATA — yfinance, Google News RSS, SEC EDGAR, Google Trends
Layer 1: MATH — Technical signals, Factor model (Fama-French), HMM regime,
         Insider signals, ML combiner (XGBoost-ready), Portfolio optimizer,
         Position sizing (Kelly), Earnings analysis, Anomaly detection
Layer 2: LLM  — Reads signal cards + news → confirms/rejects → explains
Layer 3: RISK — Stop loss, max position, cash reserve, daily loss limit,
         regime-based position scaling (all hard-coded, LLM cannot override)
Layer 4: PERFORMANCE — Sharpe ratio, max drawdown, Calmar ratio, win rate,
         profit factor, payoff ratio (computed from trading history)
Layer 5: DECISION LOG — Full pipeline data persisted to SQLite (decision_log table).
         Exposed via /api/decision/{strategy}. Frontend shows 5-step accordion
         with beginner-friendly Chinese explanations per step.
```

## Cost Estimate
~$25-30/month (LLM API ~$20 + Fly.io ~$8)

## Key Design Decisions
1. **No LangChain** — direct Anthropic/OpenAI SDK calls for simplicity
2. **SQLite** for persistence (on Fly persistent volume)
3. **Frequency-tiered scheduler** — Buffett 1hr, ARK/Balanced 30min, Momentum/Quant 15min
4. **Watchlist per strategy** — some limited to 30 stocks, some free to buy any
5. **Hybrid Math+AI architecture** — math computes signals, LLM makes final call, hard rules enforce limits
6. **News via Google News RSS** — free, no API key needed
7. **All AI reasoning in 繁體中文** — short 2-3 sentence analysis
8. **Auto-start on boot** — no manual intervention needed
9. **Auto-deploy rule** — always run fly deploy after code changes

## Testing
```bash
cd backend && pip install pytest scipy hmmlearn && python -m pytest tests/ -v --ignore=tests/test_ml_combiner.py
# 238 tests covering: portfolio, models, strategies, signals, factors,
# regime, insider, ML combiner, portfolio optimizer, risk rules,
# earnings, anomaly, performance, decision_log
```

## Known Issues
- Claude 4.6 model IDs (claude-opus-4-6, claude-sonnet-4-6) return 404 on API (using 4.0 for now). Retry periodically.
- Performance chart shows bar comparison (not line chart) until enough snapshots accumulate
- recharts needs dynamic import with ssr:false to avoid Next.js build crashes
- test_ml_combiner.py excluded from test runs (scipy import issue in CI, works locally)
- Manual cycles (POST /api/cycle) now use full quant pipeline + save decision logs (fixed 2026-04-02)
- Strategy prompts updated to be more aggressive (min 40-60% capital deployed)

## Previous Project (deprecated)
There is an older `ai-stock-analyst/` project in the same parent directory using Streamlit.
It's been superseded by this `ai-trader/` project. Can be deleted.
