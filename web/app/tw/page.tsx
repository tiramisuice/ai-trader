"use client"

import { useEffect, useState, useCallback } from "react"
import { StatusBar } from "@/components/status-bar"
import { Leaderboard } from "@/components/leaderboard"
import { TradeFeed } from "@/components/trade-feed"
import {
  StatusBarSkeleton,
  LeaderboardSkeleton,
  TradeFeedSkeleton,
  ChartSkeleton,
} from "@/components/dashboard-skeletons"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import type { Status, Portfolio, Trade } from "@/lib/api"
import { getStatus, getTWPortfolios, getTWTrades, runTWCycle } from "@/lib/api"
import { formatCurrencyTW, formatCurrencyTWPrecise } from "@/lib/utils"

const REFRESH_INTERVAL = 30_000

export default function TWDashboardPage() {
  const [status, setStatus] = useState<Status | null>(null)
  const [portfolios, setPortfolios] = useState<Portfolio[]>([])
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [chartRange, setChartRange] = useState<string>("1W")

  const fetchData = useCallback(async () => {
    try {
      const [statusData, portfoliosData, tradesData] = await Promise.all([
        getStatus(),
        getTWPortfolios(),
        getTWTrades(undefined, 20),
      ])
      setStatus(statusData)
      setPortfolios(portfoliosData)
      setTrades(tradesData)
      setError(null)
    } catch {
      setError(
        "Unable to connect to the trading backend. Is it running on localhost:8000?"
      )
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, REFRESH_INTERVAL)
    return () => clearInterval(interval)
  }, [fetchData])

  if (loading) {
    return (
      <div className="space-y-6">
        <StatusBarSkeleton />
        <LeaderboardSkeleton />
        <ChartSkeleton />
        <TradeFeedSkeleton />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Card className="max-w-md">
          <CardContent className="pt-6 text-center">
            <p className="mb-2 text-4xl">{"\u{1F50C}"}</p>
            <h2 className="mb-2 text-lg font-semibold text-foreground">
              Backend Unavailable
            </h2>
            <p className="mb-4 text-sm text-muted-foreground">{error}</p>
            <Button onClick={fetchData} variant="outline">
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Section 1: Status Bar */}
      <StatusBar
        status={status}
        onRefresh={fetchData}
        runCycleFn={runTWCycle}
        showToggle={false}
        label={"\u53F0\u80A1 Trading"}
      />

      {/* Section 2: Leaderboard */}
      <Leaderboard
        portfolios={portfolios}
        strategyBasePath="/tw/strategies"
        currencyFormatter={formatCurrencyTW}
      />

      {/* Section 3: Performance Chart */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-foreground">
            Performance
          </h2>
          <div className="flex gap-1">
            {["1D", "1W", "1M", "ALL"].map((range) => (
              <Button
                key={range}
                variant={chartRange === range ? "default" : "ghost"}
                size="xs"
                onClick={() => setChartRange(range)}
                className="font-mono text-xs"
              >
                {range}
              </Button>
            ))}
          </div>
        </div>
        <Card>
          <CardContent className="pt-6">
            {portfolios.length > 0 ? (
              <div className="space-y-3">
                {portfolios
                  .sort((a, b) => b.total_return_pct - a.total_return_pct)
                  .map((p) => (
                  <div key={p.strategy} className="flex items-center gap-3">
                    <span className="w-24 text-sm text-muted-foreground truncate">
                      {p.emoji} {p.strategy}
                    </span>
                    <div className="flex-1 h-6 bg-zinc-800 rounded-full overflow-hidden relative">
                      <div
                        className={`h-full rounded-full transition-all ${
                          p.total_return_pct >= 0 ? "bg-green-500/70" : "bg-red-500/70"
                        }`}
                        style={{
                          width: `${Math.min(Math.max(Math.abs(p.total_return_pct ?? 0) * 5 + 2, 2), 100)}%`,
                        }}
                      />
                      <span className="absolute inset-0 flex items-center justify-center text-xs font-mono text-foreground">
                        {(p.total_return_pct ?? 0) >= 0 ? "+" : ""}{(p.total_return_pct ?? 0).toFixed(2)}%
                      </span>
                    </div>
                    <span className="w-28 text-right text-sm font-mono tabular-nums text-foreground">
                      {formatCurrencyTW(p.total_value)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex h-48 items-center justify-center">
                <p className="text-sm text-muted-foreground">尚無數據</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Section 4: Recent Trades */}
      <TradeFeed trades={trades} currencyFormatter={formatCurrencyTWPrecise} />
    </div>
  )
}
