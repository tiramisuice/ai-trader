"use client"

import { useMemo } from "react"
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts"
import { Card, CardContent } from "@/components/ui/card"
import type { AgentOverview } from "@/lib/api"
import { AGENT_COLORS } from "@/lib/api"

const RANGE_MS: Record<string, number> = {
  "1D": 24 * 3600e3,
  "1W": 7 * 24 * 3600e3,
  "1M": 30 * 24 * 3600e3,
  ALL: Infinity,
}

interface EquityChartProps {
  agents: AgentOverview[]
  range: string
}

/** Multi-agent equity curve, % indexed to each agent's first visible point. */
export function EquityChart({ agents, range }: EquityChartProps) {
  const { rows, series } = useMemo(() => {
    const cutoff = Date.now() - (RANGE_MS[range] ?? Infinity)
    const buckets = new Map<number, Record<string, number>>()
    const series: { key: string; emoji: string; last: number }[] = []

    for (const a of agents) {
      const pts = a.sparkline
        .map((p) => ({ t: new Date(p.t).getTime(), v: p.v }))
        .filter((p) => p.t >= cutoff && p.v > 0)
      if (pts.length < 2) continue
      const base = pts[0].v
      let last = 0
      for (const p of pts) {
        const bucket = Math.round(p.t / 600e3) * 600e3 // 10-min buckets
        const row = buckets.get(bucket) ?? {}
        last = (p.v / base - 1) * 100
        row[a.strategy] = Number(last.toFixed(2))
        buckets.set(bucket, row)
      }
      series.push({ key: a.strategy, emoji: a.emoji, last })
    }

    const rows = [...buckets.entries()]
      .sort(([a], [b]) => a - b)
      .map(([t, vals]) => ({ t, ...vals }))
    series.sort((a, b) => b.last - a.last)
    return { rows, series }
  }, [agents, range])

  if (rows.length < 2) {
    return (
      <Card>
        <CardContent className="flex h-48 items-center justify-center pt-6">
          <p className="text-sm text-muted-foreground">
            走勢圖需要更多 snapshot 數據 — 新賽季剛開始，跑幾個小時就有了
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={rows} margin={{ top: 4, right: 56, bottom: 0, left: 0 }}>
            <XAxis
              dataKey="t"
              type="number"
              domain={["dataMin", "dataMax"]}
              scale="time"
              tickFormatter={(t: number) =>
                new Date(t).toLocaleDateString("zh-TW", { month: "numeric", day: "numeric" })
              }
              stroke="#52525b"
              fontSize={11}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v}%`}
              stroke="#52525b"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              width={52}
            />
            <ReferenceLine y={0} stroke="#3f3f46" strokeDasharray="3 3" />
            <Tooltip
              labelFormatter={(t) => new Date(Number(t)).toLocaleString("zh-TW")}
              formatter={(value, name) => [
                `${Number(value) >= 0 ? "+" : ""}${value}%`,
                String(name),
              ]}
              contentStyle={{
                backgroundColor: "#27272a",
                border: "1px solid #3f3f46",
                borderRadius: 6,
                fontSize: 12,
              }}
            />
            {series.map((s) => (
              <Line
                key={s.key}
                dataKey={s.key}
                name={`${s.emoji} ${s.key}`}
                stroke={AGENT_COLORS[s.key] ?? "#71717a"}
                strokeWidth={2}
                dot={false}
                connectNulls
                isAnimationActive={false}
                label={undefined}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
        {/* Direct labels: legend row in fixed identity colors */}
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
          {series.map((s) => (
            <span key={s.key} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: AGENT_COLORS[s.key] }}
              />
              {s.emoji} {s.key}
              <span
                className={`font-mono tabular-nums ${s.last >= 0 ? "text-green-500" : "text-red-500"}`}
              >
                {s.last >= 0 ? "+" : ""}
                {s.last.toFixed(2)}%
              </span>
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
