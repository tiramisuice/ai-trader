# PLAN

## 目前狀態（2026-10-13）

- ✅ **Season 2 上線中**：2026-07-09 部署 Phase 3 並開季，已跑 96 天（資料到 2026-10-13）
  - 10 個 agent 裡 5 個贏大盤（含真實成本）；Season 1 粗估扣成本後是 3 個
  - 交易量：Season 1 約 3 個月 13,224 筆 → Season 2 約 3 個月 110 筆（少 ~99%）
  - LLM 成本約 $407（~$127/月），遠高於舊估計的 $25–30/月
  - 詳細數字見 README「Results」
- ✅ **Public release 準備**（2026-10-13）：
  - 控制類 endpoint 加 admin token（`api/api/auth.py`），前端 status bar 改唯讀
  - 英文 README（含 v1/v2 對照與結果）、MIT LICENSE、GitHub Actions CI、`api/.env.example`
  - 清掉過時的 CLAUDE.md、web boilerplate README 與未使用的 public/*.svg

## 歷史（2026-07-09）

- ✅ **Phase 3 — Soul Agents**（commit `71152db`）：
  - Agent 完全自主：拆掉風控籠子（只留物理定律 + 真實成本）、刪強迫交易 prompt、
    可 all-in、自選喚醒時間（0.25–48hr）
  - Event-driven scheduler：5 分鐘 tick；conditional orders 睡覺時自動成交；
    wake triggers / 自訂鬧鐘 / 成交事件喚醒
  - 記憶系統：journal（繁中日記）+ standing intents + 睡眠期間事件回饋
  - 新資訊：research phase（Anthropic web search，max 3 次/決策）+ 日期
    + 反舊記憶指令；agent 自管 watchlist
  - 賽季制：season 隔離數據、`api/tools/start_season.py` 開季工具
  - LLM 升級：claude-opus-4-8 / claude-sonnet-5
  - 之後把睡眠上限從 120hr 降到 48hr（commit `611f261`）

## 歷史（2026-07-08）

- ✅ **救援**：API source 從 Fly machine 完整取回、建 repo（`tiramisuice/ai-trader`）、
  108MB trading.db 備份（13,224 trades / 3 個月）
- ✅ **Phase 1 — Bug fixes**（commit `f7afd2d`）：race condition、watchlist 強制執行、
  每日虧損斷路器、開盤/假日 guard、yfinance retry、假 snapshot 防護、regime 重複
  scaling、dead code 清除、SQLite busy_timeout、記憶體上限
- ✅ **Phase 2 — 系統設計改進**（本 commit）：
  - 交易成本模型（`costs.py`）：TW 手續費+證交稅、US 滑價+SEC fee，寫入 `trades.fees`
  - Strategy prompts 告知 LLM 交易成本（抑制過度交易）
  - Batch history download（每 cycle 1 次 `yf.download` 取代 ~60 次逐檔抓取）
  - Cycle-consistent prices（LLM 看到的價格 = 成交價）
  - Benchmark endpoint：`/api/performance/benchmark/{strategy}`（vs SPY / 0050.TW）
  - LLM 成本入 DB：`llm_costs` 表 + `/api/performance/llm-costs`
- ✅ **已部署**（2026-07-09）：Phase 1+2 上線，健康檢查通過，benchmark 驗證
  （tw_ark alpha +41pp vs 0050.TW、quant +3.6pp vs SPY，皆為未含成本的歷史數字）
- ✅ **Web source 已取回**（2026-07-09）：完整 Next.js source 從舊 PC 補進 `web/`，
  `npm run build` 驗證通過；backend 與部署版 diff 確認一致（無遺漏改動）

## 下一步（優先順序）

1. **LLM 成本檢討**：~$127/月 已接近美股 5 個 agent 的帳面獲利；考慮 research phase
   次數上限、便宜 model 做初篩、或拉長預設喚醒間隔
2. **前端 Soul 化**：顯示 journal 時間軸、standing intents、喚醒排程、
   season 切換、fees、benchmark、LLM 成本
3. **前端 lint 清零**：4 個 React 19 compiler 規則錯誤（`set-state-in-effect`、
   impure render）在 market-nav / market-banner / stock page / equity-chart；修完後把
   `npm run lint` 加進 CI
4. **ai-stock-analyst 專案處置**：舊 PC zip 裡的 Streamlit 研究專案，
   待決定是否另建 repo 保存

## 未來 TODO（機會清單）

- 爆倉自動出局判定 + 賽季排行榜 API
- OpenAI agent 的 research 工具（Tavily / Finnhub client-side loop）
- 長線選股系統（獨立於本競技場，另行設計 — Jay 的個人策略是長線）
- 歷史績效重算工具：用 Season 1 的 13,224 筆 trades 回推「若含成本」的 equity curve
- `.info` 逐檔抓取優化；insider 批次化
- Scheduler 的 end-to-end mocked tick test
- 風險指標擴充：Sharpe / Sortino / 每策略 fees 累計顯示在 performance API

## 決策記錄（重要的 why）

- **成本預設開啟**（而非 opt-in）：正確性優先，寧可低估報酬也不要假象;
  測試用 `ZERO_COST_MODEL` 明確關閉
- **每日虧損基準 = 當天第一筆 snapshot**：不需額外狀態表、重啟後自動恢復；
  代價是開盤跳空不計入當日虧損（可接受）
- **開盤 guard 用 exchange-calendars**：假日表自動維護，勝過手寫假日清單;
  calendar 失敗時 fail-open（寧可多跑也不要靜默停擺）
- **cron 視窗保持寬鬆、由 guard 過濾**：cron 表達式簡單、正確性集中在一處
