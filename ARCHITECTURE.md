# ARCHITECTURE

AI 股票 paper-trading 系統：quant 訊號 + LLM 決策 + Python 硬性風控，同時操作美股與台股。

## Tech Stack

| 層 | 技術 |
|---|---|
| Backend | Python 3.13 / FastAPI / APScheduler |
| 資料 | yfinance（行情）、feedparser（新聞 RSS）、SQLite（WAL mode，Fly volume `/data`） |
| LLM | Anthropic + OpenAI（structured output：tool_use / json_schema） |
| Quant | numpy、scipy、hmmlearn（HMM regime） |
| Frontend | Next.js 16 + React 19 + Tailwind 4 + recharts（source 待從另一台 PC 補回） |
| 部署 | Fly.io（`ai-trader-api` + `ai-trader-web`，sjc region） |

## 資料流（每個 trading cycle）

```
APScheduler cron（美股 ET / 台股 Asia/Taipei，分三個頻率層級）
  └─ is_market_open() guard（exchange-calendars：XNYS / XTAI，含假日）
      └─ _run_subset()  [scheduler.py — 核心 pipeline]
          1. MATH ENGINE
             - fetch_batch_history()：一次 yf.download 抓全 universe 的 1y OHLCV
             - cycle_prices：每 cycle 一份統一報價（報告、停損、成交都用它）
             - signals（RSI/MACD/BB/ATR）→ factors（5 因子 z-score）
             - regime（HMM + rule fallback）→ insider → ml_combiner → optimizer
             - earnings、anomaly、news
          2. 風控前置：停損強制賣出 + 每日虧損斷路器（當日基準 = 今天第一筆 snapshot）
          3. LLM DECISIONS：每個 strategy 帶 persona 呼叫 LLM → TradeDecision（Pydantic 驗證）
          4. RISK RULES + EXECUTE（LLM 無法繞過）：
             - daily-loss halt → watchlist 白名單 → check_buy_order（現金保留/
               部位上限/檔數上限/單 cycle 交易數）→ ATR/Kelly sizing → regime scaling
             - execute_order()：含交易成本（手續費/證交稅/滑價，costs.py）
          5. 持久化：trades（含 fees）、portfolio_states、snapshots（缺價不寫）、
             decision_log（完整決策稽核）、llm_costs
```

## 模組地圖（api/）

- `main.py` — FastAPI app + lifespan（開機自動啟動 scheduler）
- `trading/` — `scheduler.py`（orchestrator）、`portfolio.py`（模擬帳戶）、
  `costs.py`（成本模型）、`strategies.py` / `strategies_tw.py`（10 個 LLM persona）、
  `market_hours.py`（開盤 guard）、`models.py`
- `quant/` — `signals.py`、`factors.py`、`regime.py`、`insider.py`、`ml_combiner.py`、
  `portfolio_optimizer.py`、`position_sizing.py`、`risk_rules.py`、`earnings.py`、
  `anomaly.py`、`performance.py`
- `data/` — `fetch.py`（tenacity retry 的低階 fetcher）、`batch.py`（批次下載）、
  `market.py`（報價 + cache）、`news.py`
- `llm/` — `client.py`（雙 provider + cost tracking）、`models.py`（model registry）
- `db/sqlite.py` — thread-local SQLite wrapper（busy_timeout、fees migration）
- `routes/` — health / trading / portfolio / performance（含 benchmark、llm-costs）/ decision

## 關鍵設計原則

1. **Math → LLM → Risk 三層分離**：硬性風控在 Python，LLM 只能提案不能執行
2. **每 cycle 一份 canonical price**：LLM 看到的價格 = 成交價格
3. **成本誠實**：買入 fees 資本化進 avg_cost，賣出從 proceeds 扣（TW：0.1425% 手續費
   + 0.3% 證交稅；US：5bps 滑價 + SEC fee）
4. **可稽核**：每個決策 cycle 的 pipeline/LLM input/output/風控/執行全部入 DB
5. **優雅降級**：任一資料源掛掉 → 該訊號標為 unavailable，cycle 照跑；報價抓不到
   → 保留最後已知價、跳過 snapshot

## 已知限制 / 待辦

- Frontend source 只在另一台 PC 上（Fly image 是 compiled build）
- Regime scaling 仍同時出現在 combiner 加權項與 optimizer 配置中（execution 為
  canonical；完整單一化列在 PLAN.md）
- insider/`.info` 仍為逐檔抓取（batch 只涵蓋 OHLCV）
