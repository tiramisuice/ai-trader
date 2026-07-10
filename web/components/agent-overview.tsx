"use client"

import Link from "next/link"
import { LineChart, Line, ResponsiveContainer } from "recharts"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { AgentOverview } from "@/lib/api"
import { AGENT_COLORS } from "@/lib/api"

function sleepLabel(nextWakeup: string | null): { text: string; awake: boolean } {
  if (!nextWakeup) return { text: "未初始化", awake: false }
  const ms = new Date(nextWakeup).getTime() - Date.now()
  if (ms <= 0) return { text: "⏰ 即將甦醒（下個 tick）", awake: true }
  const h = Math.floor(ms / 3600e3)
  const m = Math.round((ms % 3600e3) / 60e3)
  return { text: `😴 睡眠中 · ${h > 0 ? `${h}h ` : ""}${m}m 後醒來`, awake: false }
}

export function AgentOverviewGrid({
  agents,
  marketPath,
}: {
  agents: AgentOverview[]
  marketPath: string // "" for US, "/tw" for TW
}) {
  const symbol = agents[0]?.currency === "TWD" ? "NT$" : "$"

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {agents.map((a) => {
        const sleep = sleepLabel(a.next_wakeup)
        const color = AGENT_COLORS[a.strategy] ?? "#71717a"
        const spark = a.sparkline.slice(-60).map((p) => ({ v: p.v }))
        return (
          <Link
            key={a.strategy}
            href={`${marketPath}/strategies/${a.strategy}`}
            className="block"
          >
            <Card className="h-full transition-colors hover:border-zinc-600">
              <CardContent className="space-y-3 pt-5">
                {/* Header: identity + status */}
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-foreground">
                      {a.emoji} {a.display_name}
                    </p>
                    <p className="text-xs text-muted-foreground">{sleep.text}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono text-sm font-bold tabular-nums text-foreground">
                      {symbol}
                      {a.total_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </p>
                    <p
                      className={`font-mono text-xs tabular-nums ${
                        a.return_pct >= 0 ? "text-green-500" : "text-red-500"
                      }`}
                    >
                      {a.return_pct >= 0 ? "+" : ""}
                      {a.return_pct.toFixed(2)}%
                    </p>
                  </div>
                </div>

                {/* Sparkline */}
                <div className="h-10">
                  {spark.length >= 2 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={spark} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
                        <Line
                          dataKey="v"
                          stroke={color}
                          strokeWidth={2}
                          dot={false}
                          isAnimationActive={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="pt-3 text-center text-[10px] text-muted-foreground">
                      等待 snapshot 累積
                    </p>
                  )}
                </div>

                {/* Positions + intents summary */}
                <div className="flex flex-wrap items-center gap-1.5">
                  {a.positions.slice(0, 4).map((p) => (
                    <Badge
                      key={p.ticker}
                      variant="secondary"
                      className={`font-mono text-[10px] ${
                        p.pnl_pct >= 0
                          ? "bg-green-500/10 text-green-500"
                          : "bg-red-500/10 text-red-500"
                      }`}
                    >
                      {p.ticker} {p.pnl_pct >= 0 ? "+" : ""}
                      {p.pnl_pct.toFixed(1)}%
                    </Badge>
                  ))}
                  {a.positions.length > 4 && (
                    <span className="text-[10px] text-muted-foreground">
                      +{a.positions.length - 4}
                    </span>
                  )}
                  {a.positions.length === 0 && (
                    <span className="text-[10px] text-muted-foreground">💰 全現金觀望中</span>
                  )}
                  {a.intents.length > 0 && (
                    <Badge variant="secondary" className="bg-blue-500/10 text-blue-400 text-[10px]">
                      ⏳ {a.intents.length} 掛單/鬧鐘
                    </Badge>
                  )}
                </div>

                {/* Latest journal snippet */}
                {a.last_journal && (
                  <p className="line-clamp-2 border-l-2 border-amber-500/40 pl-2 text-xs leading-relaxed text-muted-foreground">
                    📓 {a.last_journal.entry}
                  </p>
                )}
              </CardContent>
            </Card>
          </Link>
        )
      })}
    </div>
  )
}
