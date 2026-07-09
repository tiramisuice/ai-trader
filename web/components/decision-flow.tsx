"use client"

import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "@/components/ui/accordion"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import type { DecisionFlow } from "@/lib/api"
import { formatCurrency, formatPercent } from "@/lib/utils"

const STEPS = [
  { key: "data", label: "DATA" },
  { key: "quant", label: "QUANT" },
  { key: "llm", label: "LLM" },
  { key: "risk", label: "RISK" },
  { key: "execute", label: "EXECUTE" },
] as const

/* ------------------------------------------------------------------ */
/*  Pipeline Stepper                                                   */
/* ------------------------------------------------------------------ */

function PipelineStepper({ completedCount }: { completedCount: number }) {
  return (
    <div className="flex items-center justify-center gap-0 py-4">
      {STEPS.map((step, i) => (
        <div key={step.key} className="flex items-center">
          {/* Dot */}
          <div className="flex flex-col items-center gap-1">
            <div
              className={`h-3 w-3 rounded-full ${
                i < completedCount ? "bg-blue-500" : "bg-zinc-600"
              }`}
            />
            <span className="text-[10px] font-medium text-muted-foreground">
              {step.label}
            </span>
          </div>
          {/* Connector line */}
          {i < STEPS.length - 1 && (
            <div
              className={`mx-2 h-0.5 w-10 sm:w-16 ${
                i < completedCount - 1 ? "bg-blue-500/50" : "bg-blue-500/30"
              }`}
            />
          )}
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Score bar (0-1 range)                                              */
/* ------------------------------------------------------------------ */

function ScoreBar({ value, className }: { value: number; className?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  return (
    <div className={`h-1.5 w-full rounded-full bg-zinc-700 ${className ?? ""}`}>
      <div
        className="h-full rounded-full bg-blue-500"
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Step 1 — Data Collection                                           */
/* ------------------------------------------------------------------ */

function StepData({ data }: { data: DecisionFlow }) {
  const regime = data.pipeline.regime

  return (
    <div className="space-y-3">
      {regime ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted-foreground">Market Regime:</span>
          <Badge
            variant="secondary"
            className={
              regime.current === "bull"
                ? "bg-green-500/10 text-green-500"
                : regime.current === "bear"
                  ? "bg-yellow-500/10 text-yellow-500"
                  : "bg-red-500/10 text-red-500"
            }
          >
            {regime.current.toUpperCase()}
          </Badge>
          <span className="text-xs text-muted-foreground">
            Position Scale: {(regime.position_scale * 100).toFixed(0)}%
          </span>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No regime data</p>
      )}

      {regime && Object.keys(regime.probabilities).length > 0 && (
        <div className="flex flex-wrap gap-3">
          {Object.entries(regime.probabilities).map(([key, prob]) => (
            <div key={key} className="text-xs text-muted-foreground">
              <span className="capitalize">{key}:</span>{" "}
              <span className="font-mono tabular-nums text-foreground">
                {(prob * 100).toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      )}

      {regime?.description && (
        <p className="text-sm text-muted-foreground">{regime.description}</p>
      )}

      <div className="text-xs text-muted-foreground">
        Tickers scanned:{" "}
        <span className="font-mono tabular-nums text-foreground">
          {data.pipeline.tickers_scanned}
        </span>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Step 2 — Quant Signals                                             */
/* ------------------------------------------------------------------ */

function StepQuant({ data }: { data: DecisionFlow }) {
  const signals = data.pipeline.top_signals.slice(0, 3)
  const anomalies = data.pipeline.anomalies

  return (
    <div className="space-y-4">
      {signals.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {signals.map((sig) => (
            <div
              key={sig.ticker}
              className="rounded-lg border border-zinc-800 bg-zinc-900 p-3 space-y-2"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm font-bold text-foreground">
                  {sig.ticker}
                </span>
                <Badge
                  variant="secondary"
                  className={
                    sig.signal === "buy"
                      ? "bg-green-500/10 text-green-500"
                      : sig.signal === "sell"
                        ? "bg-red-500/10 text-red-500"
                        : "bg-zinc-500/10 text-zinc-400"
                  }
                >
                  {sig.signal.toUpperCase()}
                </Badge>
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>Score</span>
                  <span className="font-mono tabular-nums text-foreground">
                    {sig.combined_score.toFixed(2)}
                  </span>
                </div>
                <ScoreBar value={sig.combined_score} />
              </div>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between text-muted-foreground">
                  <span>Tech</span>
                  <span className="font-mono tabular-nums">
                    {sig.breakdown.technical.toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between text-muted-foreground">
                  <span>Factor</span>
                  <span className="font-mono tabular-nums">
                    {sig.breakdown.factor.toFixed(2)}
                  </span>
                </div>
                <div className="flex justify-between text-muted-foreground">
                  <span>Insider</span>
                  <span className="font-mono tabular-nums">
                    {sig.breakdown.insider.toFixed(2)}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No signals available</p>
      )}

      {anomalies.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">
            Anomalies ({anomalies.length})
          </p>
          <div className="flex flex-wrap gap-2">
            {anomalies.map((a, i) => (
              <Badge
                key={i}
                variant="secondary"
                className={
                  a.severity === "high"
                    ? "bg-red-500/10 text-red-500"
                    : a.severity === "medium"
                      ? "bg-yellow-500/10 text-yellow-500"
                      : "bg-zinc-500/10 text-zinc-400"
                }
              >
                {a.ticker} &mdash; {a.type}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Step 3 — AI Decision                                               */
/* ------------------------------------------------------------------ */

function StepLLM({ data }: { data: DecisionFlow }) {
  const { market_analysis, reasoning, orders_proposed } = data.llm_output
  const journal = data.llm_output.journal
  const conditionals = data.llm_output.conditional_orders ?? []
  const wakeTriggers = data.llm_output.wake_triggers ?? []
  const nextCheck = data.llm_output.next_check_hours
  const wakeReason = data.llm_input.wake_reason

  return (
    <div className="space-y-4">
      {wakeReason && (
        <div className="rounded-lg border border-blue-500/20 bg-blue-500/5 p-4">
          <p className="mb-1 text-xs font-medium text-blue-400">
            &#x270B; Wake Reason 甦醒原因
          </p>
          <p className="text-sm leading-relaxed text-foreground">{wakeReason}</p>
        </div>
      )}

      {market_analysis && (
        <div className="rounded-lg bg-zinc-800 p-4">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            Market Analysis
          </p>
          <p className="text-sm leading-relaxed text-foreground">
            {market_analysis}
          </p>
        </div>
      )}

      {reasoning && (
        <div className="rounded-lg bg-zinc-800 p-4">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            Reasoning
          </p>
          <p className="text-sm leading-relaxed text-foreground">{reasoning}</p>
        </div>
      )}

      {journal && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-4">
          <p className="mb-1 text-xs font-medium text-amber-400">
            &#x1F4D3; Trading Journal 交易日記
          </p>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
            {journal}
          </p>
        </div>
      )}

      {(conditionals.length > 0 || wakeTriggers.length > 0 || nextCheck !== undefined) && (
        <div className="rounded-lg bg-zinc-800 p-4 space-y-2">
          <p className="text-xs font-medium text-muted-foreground">
            &#x23F0; Standing Intents 掛單與鬧鐘
          </p>
          {conditionals.map((c, i) => (
            <p key={`c${i}`} className="font-mono text-xs text-foreground">
              {c.action} {c.ticker} x{c.shares} when {c.trigger}{" "}
              {c.trigger_price} ({c.good_for_days}d) — {c.reason}
            </p>
          ))}
          {wakeTriggers.map((w, i) => (
            <p key={`w${i}`} className="font-mono text-xs text-foreground">
              WAKE me when {w.ticker} {w.condition} {w.price}
            </p>
          ))}
          {nextCheck !== undefined && (
            <p className="text-xs text-muted-foreground">
              下次自主檢查：{nextCheck} 小時後
            </p>
          )}
        </div>
      )}

      {orders_proposed.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">
            Proposed Orders ({orders_proposed.length})
          </p>
          <div className="space-y-2">
            {orders_proposed.map((order, i) => (
              <div
                key={i}
                className="flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-900 p-3"
              >
                <Badge
                  variant="secondary"
                  className={
                    order.action === "BUY"
                      ? "bg-green-500/10 text-green-500"
                      : "bg-red-500/10 text-red-500"
                  }
                >
                  {order.action}
                </Badge>
                <div className="flex-1 space-y-1">
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-sm font-bold text-foreground">
                      {order.ticker}
                    </span>
                    <span className="font-mono text-xs tabular-nums text-muted-foreground">
                      {order.shares} shares
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">{order.reason}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No orders proposed</p>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Step 4 — Risk Rules                                                */
/* ------------------------------------------------------------------ */

function StepRisk({ data }: { data: DecisionFlow }) {
  const orders_approved = data.risk_check.orders_approved ?? []
  const orders_blocked = data.risk_check.orders_blocked ?? []
  const orders_rejected = data.risk_check.orders_rejected ?? []
  const isSoulEra = data.risk_check.orders_approved === undefined

  // Soul era (season 2+): no risk cage — only physics rejections exist
  if (isSoulEra) {
    return (
      <div className="space-y-2">
        {orders_rejected.length > 0 ? (
          <>
            <p className="text-xs font-medium text-red-500">
              Rejected by physics ({orders_rejected.length})
            </p>
            {orders_rejected.map((r, i) => (
              <div
                key={i}
                className="flex items-start gap-3 rounded-lg border border-red-500/20 bg-red-500/5 p-3"
              >
                <Badge
                  variant="secondary"
                  className={
                    r.order.action === "BUY"
                      ? "bg-green-500/10 text-green-500"
                      : "bg-red-500/10 text-red-500"
                  }
                >
                  {r.order.action}
                </Badge>
                <div className="flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-sm font-bold text-foreground">
                      {r.order.ticker}
                    </span>
                    <span className="font-mono text-xs tabular-nums text-muted-foreground">
                      {r.order.shares} shares
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-red-400">{r.why}</p>
                </div>
              </div>
            ))}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            Agent 完全自主 — 只有物理定律（現金/持股/做空）會擋單，本次無違規 ✅
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Approved */}
      <div className="space-y-2">
        <p className="text-xs font-medium text-green-500">
          Approved ({orders_approved.length})
        </p>
        {orders_approved.length > 0 ? (
          <div className="space-y-2">
            {orders_approved.map((order, i) => (
              <div
                key={i}
                className="flex items-start gap-3 rounded-lg border border-green-500/20 bg-green-500/5 p-3"
              >
                <Badge
                  variant="secondary"
                  className={
                    order.action === "BUY"
                      ? "bg-green-500/10 text-green-500"
                      : "bg-red-500/10 text-red-500"
                  }
                >
                  {order.action}
                </Badge>
                <div className="flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-sm font-bold text-foreground">
                      {order.ticker}
                    </span>
                    <span className="font-mono text-xs tabular-nums text-muted-foreground">
                      {order.shares} shares
                    </span>
                    {order.original_shares !== order.shares && (
                      <span className="text-xs text-yellow-500">
                        (was {order.original_shares})
                      </span>
                    )}
                  </div>
                  {order.adjustments.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {order.adjustments.map((adj, j) => (
                        <Badge
                          key={j}
                          variant="secondary"
                          className="bg-yellow-500/10 text-yellow-500 text-[10px]"
                        >
                          {adj}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      {/* Blocked */}
      {orders_blocked.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-medium text-red-500">
            Blocked ({orders_blocked.length})
          </p>
          <div className="space-y-2">
            {orders_blocked.map((order, i) => (
              <div
                key={i}
                className="flex items-start gap-3 rounded-lg border border-red-500/20 bg-red-500/5 p-3"
              >
                <Badge
                  variant="secondary"
                  className={
                    order.action === "BUY"
                      ? "bg-green-500/10 text-green-500"
                      : "bg-red-500/10 text-red-500"
                  }
                >
                  {order.action}
                </Badge>
                <div className="flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-sm font-bold text-foreground">
                      {order.ticker}
                    </span>
                    <span className="font-mono text-xs tabular-nums text-muted-foreground">
                      {order.shares} shares
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-red-400">{order.reason}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          All orders passed risk check &#x2705;
        </p>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Step 5 — Execution                                                 */
/* ------------------------------------------------------------------ */

function StepExecution({ data }: { data: DecisionFlow }) {
  const { trades_executed, portfolio_after } = data.execution
  const returnColor =
    portfolio_after.return_pct >= 0 ? "text-green-500" : "text-red-500"

  return (
    <div className="space-y-4">
      <div className="text-sm text-muted-foreground">
        Trades executed:{" "}
        <span className="font-mono tabular-nums text-foreground">
          {trades_executed.length}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <p className="text-xs text-muted-foreground">Portfolio Value</p>
          <p className="font-mono text-lg font-bold tabular-nums text-foreground">
            {formatCurrency(portfolio_after.total_value)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Cash</p>
          <p className="font-mono text-lg font-bold tabular-nums text-foreground">
            {formatCurrency(portfolio_after.cash)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Return</p>
          <p
            className={`font-mono text-lg font-bold tabular-nums ${returnColor}`}
          >
            {formatPercent(portfolio_after.return_pct)}
          </p>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

export function DecisionFlowComponent({
  data,
}: {
  data: DecisionFlow | null
}) {
  if (!data) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground">
          &#x5C1A;&#x7121;&#x6C7A;&#x7B56;&#x6578;&#x64DA;&#x3002;&#x7B49;&#x5F85;&#x4E0B;&#x4E00;&#x500B;&#x4EA4;&#x6613;&#x9031;&#x671F;&#x3002;
        </CardContent>
      </Card>
    )
  }

  // Determine how many steps are "complete" based on available data
  let completedCount = 1 // data collection always present if we have data
  if (data.pipeline.top_signals.length > 0 || data.pipeline.tickers_scanned > 0)
    completedCount = 2
  if (data.llm_output.market_analysis || data.llm_output.orders_proposed.length > 0)
    completedCount = 3
  if (
    (data.risk_check.orders_approved?.length ?? 0) > 0 ||
    (data.risk_check.orders_blocked?.length ?? 0) > 0 ||
    data.risk_check.orders_rejected !== undefined
  )
    completedCount = 4
  if (data.execution.trades_executed.length >= 0 && data.execution.portfolio_after)
    completedCount = 5

  return (
    <div className="space-y-2">
      <PipelineStepper completedCount={completedCount} />

      <Accordion defaultValue={[2]}>
        {/* Step 1: Data Collection */}
        <AccordionItem value={0}>
          <AccordionTrigger className="text-sm">
            <span className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-blue-500" />
              Step 1 &mdash; Data Collection
            </span>
          </AccordionTrigger>
          <AccordionContent>
            <p className="text-xs text-muted-foreground mb-3">{"📖 這是 AI 收集到的市場數據。Regime（市場狀態）告訴我們現在是牛市（適合買入）還是熊市（需要謹慎），幫助決定要投資多少比例的資金。"}</p>
            <StepData data={data} />
          </AccordionContent>
        </AccordionItem>

        {/* Step 2: Quant Signals */}
        <AccordionItem value={1}>
          <AccordionTrigger className="text-sm">
            <span className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-blue-500" />
              Step 2 &mdash; Quant Signals
            </span>
          </AccordionTrigger>
          <AccordionContent>
            <p className="text-xs text-muted-foreground mb-3">{"📖 量化引擎用數學公式（RSI、MACD、均線等）給每支股票打分。分數越高代表越值得買。Technical = 技術面分析，Factor = 基本面分析，Insider = 公司內部人買賣動向。"}</p>
            <StepQuant data={data} />
          </AccordionContent>
        </AccordionItem>

        {/* Step 3: AI Decision (DEFAULT OPEN) */}
        <AccordionItem value={2}>
          <AccordionTrigger className="text-sm">
            <span className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-blue-500" />
              Step 3 &mdash; AI Decision
            </span>
          </AccordionTrigger>
          <AccordionContent>
            <p className="text-xs text-muted-foreground mb-3">{"📖 AI 讀完所有數學信號和新聞後，用自己的判斷決定要買什麼、賣什麼。這是 AI 的「思考過程」— 你可以看到它為什麼做出這個決定。"}</p>
            <StepLLM data={data} />
          </AccordionContent>
        </AccordionItem>

        {/* Step 4: Risk Rules */}
        <AccordionItem value={3}>
          <AccordionTrigger className="text-sm">
            <span className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-blue-500" />
              Step 4 &mdash; Risk Rules
            </span>
          </AccordionTrigger>
          <AccordionContent>
            <p className="text-xs text-muted-foreground mb-3">{"📖 風險管理系統檢查 AI 的決定是否安全。如果一次買太多會被自動縮減，如果違反規則（例如單支股票超過 portfolio 的 25%）會被擋下。這保護你不會因為一次錯誤虧太多。"}</p>
            <StepRisk data={data} />
          </AccordionContent>
        </AccordionItem>

        {/* Step 5: Execution */}
        <AccordionItem value={4}>
          <AccordionTrigger className="text-sm">
            <span className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-blue-500" />
              Step 5 &mdash; Execution
            </span>
          </AccordionTrigger>
          <AccordionContent>
            <p className="text-xs text-muted-foreground mb-3">{"📖 最後實際執行交易的結果。這裡顯示真正成交了什麼（價格、數量），以及交易後整個 portfolio 的狀態。"}</p>
            <StepExecution data={data} />
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  )
}
