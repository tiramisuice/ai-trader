# PLAN

## 目前狀態（2026-07-08）

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
- ⚠️ **尚未部署**：以上修改都在 GitHub，Fly 上仍是舊版 code

## 下一步（優先順序）

1. **部署到 Fly**（`fly deploy` in `api/`）— 讓 Phase 1+2 生效；部署後觀察幾個
   cycle 確認 scheduler、斷路器、成本記帳正常
2. **從另一台 PC 取回 web source** → 補進 `web/`，之後 frontend 顯示 fees、
   benchmark 對照、LLM 成本
3. **重新評估策略績效**：跑 2-4 週含成本的數據後，用 `trades.fees` 和 benchmark
   alpha 判斷哪些 strategy 值得留（tw_quant / tw_aggressive 的高週轉在含成本後
   預期會大幅退化）

## 未來 TODO（機會清單）

- Regime scaling 完全單一化（移除 optimizer 內的 regime 乘數，只留 execution）
- `.info` 逐檔抓取優化（fast_info 或欄位級快取）；insider 批次化
- Scheduler 的 end-to-end mocked cycle test（回歸防護的最後一塊）
- 歷史績效重算工具：用既有 13,224 筆 trades 回推「若含成本」的真實 equity curve
- LLM model 選型檢討：對照官方 pricing 更新 `llm/models.py` 常數；考慮低頻策略
  用較便宜的 model
- 風險指標擴充：Sharpe / Sortino / 每策略 fees 累計顯示在 performance API
- 前端：benchmark 對照圖、決策稽核 viewer（decision_log 已有完整資料）

## 決策記錄（重要的 why）

- **成本預設開啟**（而非 opt-in）：正確性優先，寧可低估報酬也不要假象;
  測試用 `ZERO_COST_MODEL` 明確關閉
- **每日虧損基準 = 當天第一筆 snapshot**：不需額外狀態表、重啟後自動恢復；
  代價是開盤跳空不計入當日虧損（可接受）
- **開盤 guard 用 exchange-calendars**：假日表自動維護，勝過手寫假日清單;
  calendar 失敗時 fail-open（寧可多跑也不要靜默停擺）
- **cron 視窗保持寬鬆、由 guard 過濾**：cron 表達式簡單、正確性集中在一處
