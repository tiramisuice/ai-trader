# DECISIONS

重要技術與產品決策記錄（what / why / alternatives considered）。

## 2026-10-19 — 修正 Claude 決策失敗、升級 model、開 Season 3

**What**：
- Anthropic 決策從「強制 tool_choice + 不受限 schema」改為 structured outputs（`output_config.format`，
  grammar-constrained JSON）。schema 轉成 Anthropic 支援的子集：全部欄位 required、
  `additionalProperties: false`、數值上下限移到 description。`strategy` / `timestamp` 不再暴露給 LLM。
- `next_check_hours` 超出範圍改為 clamp，不再讓整份決策作廢。
- Model 升級（同價位最新）：claude-opus-5-5（$4/$20）、claude-sonnet-5-5（$2/$10）、gpt-6.1-sol（$2/$10），
  全部 medium effort。`max_tokens` 提高到 16000（thinking / reasoning token 算在內）。
- 成本記錄修正：Sonnet 5 原本被記成 $3/$15（實際 $2/$10）、GPT-5.4 output 記成 $10（實際 $15）；
  web search 費用改為寫入 DB。
- 開 Season 3（Season 2 封存；開季前 DB 備份到 `/data/trading-s2-final-20261019.db` 和本機 `recovered/`）。

**Why**：Season 2 最後 4 週，Opus 196 次呼叫只有 14 次成功決策。Opus 常只回一張 TradeOrder 形狀的
JSON（~130 output tokens），驗證失敗後「睡 1 小時重試」，每次都重跑 research + decide。失敗呼叫約占
LLM 費用 58%（每週約 $14）。另外 Opus 5.5 / Sonnet 5.5 直接拒絕強制 tool_choice（400），升級必須換做法。
開新賽季是因為 Season 2 的 Opus agent 大部分時間無法決策，結果混入新 model 會無法比較。

**Alternatives considered**：只加 retry（否決：治標，仍燒 research 成本）；改用 Fable 5.1 / GPT-6 Astra
（否決：每週成本約翻倍以上，使用者選同價位）；不開新季直接換 model（否決：結果無法解讀）。

## 2026-10-13 — 控制類 endpoint 加 admin token，repo 改為 public

**What**：`POST /api/start`、`/api/stop`、`/api/cycle`、`/api/cycle/tw` 需要 `X-Admin-Token`
header（對 `ADMIN_TOKEN` Fly secret 做 constant-time 比對）；沒設定 token 時回 503（fail closed）。
前端 status bar 改為唯讀（拿掉 Start / Stop / Run Now 按鈕）。repo 加上英文 README、MIT LICENSE、
GitHub Actions CI 後改為 public。

**Why**：原本這些 endpoint 完全沒驗證，任何訪客都能停掉實驗或觸發付費的 LLM 呼叫（每輪多次
Opus / Sonnet 呼叫）。repo 公開後 endpoint 一目了然，風險變高，必須先鎖。

**Alternatives considered**：把 token 放進前端 `NEXT_PUBLIC_*` 變數保留按鈕（否決：會直接曝光
在瀏覽器 bundle）；只靠 CORS 擋（否決：CORS 只擋瀏覽器，curl 照樣能打）；完整 user auth
（否決：只有一個管理者，殺雞用牛刀）。

## 2026-07-09 — Phase 3「Soul Agents」：拆掉風控籠子，agent 完全自主

**What**：刪除 `risk_rules.py` 與所有執行層風控（部位上限、強制停損、每日虧損斷路器、
Kelly/regime 縮單、watchlist 白名單）。執行層只保留「物理定律」：現金不能負、不能做空、
不能賣沒有的股票，加上真實交易成本。風險紀律改寫進各 persona 的自我信念。

**Why**：這是 paper-money 競技實驗，目標是觀察「有靈魂的交易者」— 強迫交易的 prompt
和外部籠子會把 10 個 persona 壓成同一個平庸系統。爆倉本身就是有價值的實驗數據（賽季制
承接後果）。**若未來接真錢，籠子必須先裝回來**（git history 保有 `risk_rules.py`）。

**Alternatives considered**：保留可調鬆緊的風控參數（否決：仍是外部意志）；
每 persona 各自的硬性上限（否決：上限應是信念不是規則）。

## 2026-07-09 — Event-driven scheduler（tick + 自主喚醒）取代固定輪詢

**What**：15/30/60 分鐘的固定 cron 輪詢改為每 5 分鐘的便宜 tick：執行已觸發的
conditional orders（不叫醒 agent）、檢查喚醒條件（自訂時間 / price trigger / 成交事件），
只有被喚醒的 agent 才呼叫 LLM。agent 自己決定下次醒來時間（0.25–120 小時）。

**Why**：真實交易者自己決定何時出手；被輪詢的 agent 沒有連續意志。同時大幅降低 LLM
呼叫次數（原本每天 ~115 次淺呼叫 → 事件驅動的深呼叫）。

## 2026-07-09 — Agent 記憶：journal + 意圖回饋

**What**：每次決策 agent 寫 journal（繁中日記），下次喚醒時餵回最近 5 篇 + 未完成
intents + 睡眠期間的成交 + 績效狀態。每次決策**取代**全部舊 intents（要保留須重述）。

**Why**：連續人格的最小可行實作。「取代式」intents 語義最簡單且無歧義（否決過
增量式 cancel/add：LLM 容易搞混 id）。

## 2026-07-09 — 新資訊管道：web search research phase（兩階段呼叫）

**What**：決策前先跑一個自由格式的 research 呼叫（Anthropic `web_search_20250305`，
max 3 searches，$0.01/次），研究筆記塞進決策 prompt。決策呼叫維持 forced structured output。

**Why**：structured output 會強制 `tool_choice`，與 server-side search 衝突，必須分兩段。
OpenAI 系 model 暫不支援（research 回空字串），之後可補 Tavily 等 client-side 工具。

## 2026-07-09 — 賽季制（Season 2 起跑）

**What**：`meta.current_season` + trades/snapshots/decision_log 的 season 欄位；
portfolio_states 以 `name@s1` 改名封存。歸零重開，舊數據完整保留為 baseline。

**Why**：拆籠子後行為劇變，混在同一份數據裡無法比較；且 agent 有了 all-in 自由後
爆倉出局需要「下一季重生」的敘事框架。

## 2026-07-09 — LLM 升級：claude-opus-4-8 / claude-sonnet-5

**What**：registry 從 legacy 的 opus-4-6 / sonnet-4-6 升到 opus-4-8（$5/$25）/
sonnet-5（$3/$15），同價位更強。模型 ID 與定價對照官方 docs（2026-07-09 驗證）。

## 2026-07-08 — 交易成本預設開啟（Phase 2）

**What**：TW 0.1425% 手續費（min NT$20）+ 賣出 0.3% 證交稅；US 5bps 滑價 + SEC fee。
買入 fees 資本化進 avg_cost。測試用 `ZERO_COST_MODEL` 顯式關閉。

**Why**：正確性優先 — 未含成本的績效是虛構的（tw_quant 帳面 +40% 實際會被 35% 費用吃掉）。

## 2026-07-08 — 開盤 guard 用 exchange-calendars、cron 寬鬆 + guard 過濾（Phase 1）

**What**：XNYS/XTAI 日曆（含假日），calendar 失敗時 fail-open。

**Why**：假日表自動維護；正確性集中在 guard 一處，cron 保持簡單。
