"use client"

import { useCallback, useEffect, useState } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { StockDetail, StockRange } from "@/lib/api"
import { getStockDetail } from "@/lib/api"
import { getStockName } from "@/lib/stock-names"

const RANGES: StockRange[] = ["1mo", "3mo", "6mo", "1y", "2y"]

function fmtBig(n: number | null): string {
  if (n == null) return "—"
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  return n.toLocaleString()
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg bg-zinc-900 p-3">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="font-mono text-sm font-semibold tabular-nums text-foreground">{value}</p>
      {hint && <p className="text-[10px] text-muted-foreground">{hint}</p>}
    </div>
  )
}

export default function StockPage() {
  const params = useParams<{ ticker: string }>()
  const ticker = decodeURIComponent(params.ticker ?? "").toUpperCase()
  const [range, setRange] = useState<StockRange>("6mo")
  const [data, setData] = useState<StockDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setData(await getStockDetail(ticker, range))
      setError(null)
    } catch {
      setError(`無法載入 ${ticker} 的資料`)
    }
  }, [ticker, range])

  useEffect(() => {
    load()
  }, [load])

  if (error) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">{error}</CardContent>
      </Card>
    )
  }
  if (!data) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-muted-foreground">載入中…</CardContent>
      </Card>
    )
  }

  const up = data.stats.return_range_pct >= 0
  const lineColor = up ? "#22c55e" : "#ef4444"
  const isTW = ticker.endsWith(".TW")
  const symbol = isTW ? "NT$" : "$"
  const localName = getStockName(ticker)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-foreground">
            <span className="font-mono">{ticker}</span>
            <span className="ml-3 text-base font-normal text-muted-foreground">
              {localName || data.name}
            </span>
          </h1>
        </div>
        <div className="text-right">
          <p className="font-mono text-2xl font-bold tabular-nums text-foreground">
            {symbol}
            {data.quote.price.toLocaleString()}
          </p>
          <p
            className={`font-mono text-sm tabular-nums ${
              data.quote.day_change_pct >= 0 ? "text-green-500" : "text-red-500"
            }`}
          >
            {data.quote.day_change_pct >= 0 ? "▲" : "▼"} {Math.abs(data.quote.day_change_pct)}% 今日
          </p>
        </div>
      </div>

      {/* 走勢圖 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            {range} 走勢：
            <span className={`font-mono ${up ? "text-green-500" : "text-red-500"}`}>
              {up ? "+" : ""}
              {data.stats.return_range_pct}%
            </span>
          </p>
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <Button
                key={r}
                variant={range === r ? "default" : "ghost"}
                size="xs"
                onClick={() => setRange(r)}
                className="font-mono text-xs"
              >
                {r}
              </Button>
            ))}
          </div>
        </div>
        <Card>
          <CardContent className="pt-6">
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={data.chart} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="stockFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={lineColor} stopOpacity={0.25} />
                    <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="date"
                  stroke="#52525b"
                  fontSize={11}
                  tickLine={false}
                  minTickGap={40}
                />
                <YAxis
                  domain={["auto", "auto"]}
                  stroke="#52525b"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  width={64}
                  tickFormatter={(v: number) => `${symbol}${v.toLocaleString()}`}
                />
                <Tooltip
                  formatter={(v) => [`${symbol}${Number(v).toLocaleString()}`, "收盤"]}
                  contentStyle={{
                    backgroundColor: "#27272a",
                    border: "1px solid #3f3f46",
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
                <Area
                  dataKey="close"
                  stroke={lineColor}
                  strokeWidth={2}
                  fill="url(#stockFill)"
                  dot={false}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Key stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <Stat label="52 週高" value={`${symbol}${data.stats.high_52w.toLocaleString()}`} />
        <Stat label="52 週低" value={`${symbol}${data.stats.low_52w.toLocaleString()}`} />
        <Stat label="SMA20" value={data.stats.sma20 ? `${symbol}${data.stats.sma20.toLocaleString()}` : "—"} />
        <Stat label="SMA50" value={data.stats.sma50 ? `${symbol}${data.stats.sma50.toLocaleString()}` : "—"} />
        <Stat
          label="RSI(14)"
          value={data.stats.rsi14 != null ? String(data.stats.rsi14) : "—"}
          hint={
            data.stats.rsi14 == null ? undefined
            : data.stats.rsi14 > 70 ? "超買" : data.stats.rsi14 < 30 ? "超賣" : "中性"
          }
        />
        <Stat label="市值" value={fmtBig(data.quote.market_cap)} />
        <Stat label="P/E" value={data.quote.pe_ratio ? data.quote.pe_ratio.toFixed(1) : "—"} />
        <Stat label="成交量" value={fmtBig(data.quote.volume)} />
      </div>

      {/* Who holds it */}
      <Card>
        <CardContent className="pt-5">
          <p className="mb-3 text-sm font-semibold text-foreground">🤖 持有這檔的 Agent</p>
          {data.holders.length > 0 ? (
            <div className="space-y-2">
              {data.holders.map((h) => (
                <Link
                  key={h.strategy}
                  href={`${h.market === "tw" ? "/tw" : ""}/strategies/${h.strategy}`}
                  className="flex items-center justify-between rounded-lg border border-zinc-800 p-3 hover:border-zinc-600"
                >
                  <span className="text-sm text-foreground">
                    {h.emoji} {h.display_name}
                  </span>
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">
                    {h.shares} 股 @ {symbol}
                    {h.avg_cost.toLocaleString()}
                    <span className={`ml-2 ${h.pnl_pct >= 0 ? "text-green-500" : "text-red-500"}`}>
                      {h.pnl_pct >= 0 ? "+" : ""}
                      {h.pnl_pct}%
                    </span>
                  </span>
                </Link>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">目前沒有 agent 持有</p>
          )}
        </CardContent>
      </Card>

      {/* Standing intents on this stock */}
      {data.intents.length > 0 && (
        <Card>
          <CardContent className="pt-5">
            <p className="mb-3 text-sm font-semibold text-foreground">⏳ 這檔股票的掛單與鬧鐘</p>
            <div className="space-y-1">
              {data.intents.map((it, i) => (
                <p key={i} className="font-mono text-xs text-muted-foreground">
                  <span className="text-foreground">{it.strategy}</span>
                  {" — "}
                  {it.kind === "wake_trigger" ? "WAKE" : it.action} {it.shares ? `x${it.shares} ` : ""}
                  when {it.trigger_type} {symbol}
                  {it.trigger_price.toLocaleString()}
                  {it.reason ? ` — ${it.reason}` : ""}
                </p>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent trades on this ticker */}
      <Card>
        <CardContent className="pt-5">
          <p className="mb-3 text-sm font-semibold text-foreground">📜 最近交易（本賽季）</p>
          {data.recent_trades.length > 0 ? (
            <div className="space-y-1">
              {data.recent_trades.map((t) => (
                <div key={t.id} className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">
                    {new Date(t.timestamp).toLocaleString("zh-TW")}
                    <span className="ml-2 text-foreground">{t.strategy}</span>
                  </span>
                  <span className="font-mono tabular-nums">
                    <span className={t.action === "BUY" ? "text-green-500" : "text-red-500"}>
                      {t.action}
                    </span>{" "}
                    {t.shares} @ {symbol}
                    {t.price.toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">本賽季還沒有交易紀錄</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
