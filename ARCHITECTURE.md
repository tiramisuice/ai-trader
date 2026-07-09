# ARCHITECTURE

AI 股票 paper-trading 競技場：10 個有「靈魂」的自主 AI trader（quant 訊號 + live web
research + 記憶 + 自主意志），同時操作美股與台股。賽季制：爆倉出局，下季重生。

## Tech Stack

| 層 | 技術 |
|---|---|
| Backend | Python 3.13 / FastAPI / APScheduler |
| 資料 | yfinance（行情）、feedparser（新聞 RSS）、SQLite（WAL mode，Fly volume `/data`） |
| LLM | Anthropic + OpenAI（structured output：tool_use / json_schema） |
| Quant | numpy、scipy、hmmlearn（HMM regime） |
| Frontend | Next.js 16 + React 19 + Tailwind 4 + recharts（source 待從另一台 PC 補回） |
| 部署 | Fly.io（`ai-trader-api` + `ai-trader-web`，sjc region） |

## 資料流（event-driven tick loop）

```
APScheduler tick（每 5 分鐘，美股 ET / 台股 Asia/Taipei 各一）
  └─ is_market_open() guard（exchange-calendars：XNYS / XTAI，含假日）
      └─ _tick()  [scheduler.py]
          1. 過期 intents 清理 + 抓 intents/持股相關報價（便宜，無 LLM）
          2. CONDITIONAL FILLS：已觸發的條件單直接成交（agent 睡覺中，
             系統只是履行它的預先承諾）
          3. 喚醒判定：自訂鬧鐘到了 / wake trigger 命中 / 條件單成交
             → 只有被喚醒的 agent 走下面流程
          4. MATH ENGINE（只為醒著的 agent 的 universe 算一次）：
             batch OHLCV → signals / factors / regime / insider / combiner /
             earnings / anomaly；cycle_prices 統一報價
          5. RESEARCH PHASE：agent 用 live web search 自主研究（Anthropic
             web_search tool，max 3 searches；要不要查是個性的一部分）
          6. DECIDE：喚醒 context（日記、standing intents、睡眠期間成交、
             績效、自管 watchlist）+ 研究筆記 → TradeDecision（Pydantic）
          7. EXECUTE（只有物理定律）：現金不能負、不能做空、不能賣沒有的，
             加真實交易成本（costs.py）。沒有部位上限、沒有強制停損。
          8. 持久化 agent 的延續性：journal、新 intents（取代舊的）、
             watchlist、next_wakeup、portfolio、snapshot、decision_log
```

## 模組地圖（api/）

- `main.py` — FastAPI app + lifespan（開機自動啟動 scheduler）
- `trading/` — `scheduler.py`（tick loop + 喚醒管理）、`portfolio.py`（模擬帳戶，
  物理定律在這）、`costs.py`（成本模型）、`strategies.py` / `strategies_tw.py`
  （10 個 persona + 自主權宣言 + research/decide 兩階段）、
  `market_hours.py`（開盤 guard）、`models.py`（含 ConditionalOrder / WakeTrigger）
- `quant/` — `signals.py`、`factors.py`、`regime.py`、`insider.py`、`ml_combiner.py`、
  `portfolio_optimizer.py`、`position_sizing.py`、`earnings.py`、`anomaly.py`、
  `performance.py`（optimizer/sizing 目前不在主 pipeline，保留為工具）
- `data/` — `fetch.py`（tenacity retry）、`batch.py`（批次下載）、`market.py`、`news.py`
- `llm/` — `client.py`（雙 provider + `research()` web search + cost tracking）、
  `models.py`（registry：claude-opus-4-8 / claude-sonnet-5 / gpt-5.4）
- `db/sqlite.py` — SQLite wrapper（seasons、intents、journal、agent_state、llm_costs）
- `tools/start_season.py` — 開新賽季（封存 portfolio、歸零重開）
- `routes/` — health / trading（status 含 season + agent 喚醒排程）/ portfolio /
  performance（benchmark、llm-costs）/ decision

## 關鍵設計原則

1. **Agent 自主**：不強迫交易、自選喚醒時間、條件單睡覺時自動成交、自管 watchlist、
   可以 all-in — 風險紀律是 persona 信念，不是外部規則（真錢前必須裝回籠子）
2. **記憶**：journal + standing intents + 睡眠期間事件回饋 → 連續人格
3. **新資訊**：prompt 給今日日期 + 反舊記憶指令；research phase 用 live web search
4. **物理與成本誠實**：執行層只擋物理違規；fees 資本化/扣除（TW 手續費+證交稅、US 滑價）
5. **可稽核**：research、journal、intents、決策、執行全部入 DB（decision_log + journal + intents）
6. **賽季制**：season 欄位隔離數據；爆倉出局，下季帶記憶重生
7. **優雅降級**：資料源掛掉 → 訊號標 unavailable；報價抓不到 → 保留最後已知價、跳過 snapshot

## 已知限制 / 待辦

- OpenAI 系 agent 的 research phase 尚未支援（回空字串）— 可補 Tavily/Finnhub
- 賽季自動判定爆倉出局尚未實作（目前人工開季）
- insider/`.info` 仍為逐檔抓取（batch 只涵蓋 OHLCV）
