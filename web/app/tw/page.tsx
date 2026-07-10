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
import { AgentOverviewGrid } from "@/components/agent-overview"
import { EquityChart } from "@/components/equity-chart"
import type { Status, Portfolio, Trade, AgentOverview } from "@/lib/api"
import { getStatus, getTWPortfolios, getTWTrades, runTWCycle, getOverview } from "@/lib/api"
import { formatCurrencyTW, formatCurrencyTWPrecise } from "@/lib/utils"

const REFRESH_INTERVAL = 30_000

export default function TWDashboardPage() {
  const [status, setStatus] = useState<Status | null>(null)
  const [portfolios, setPortfolios] = useState<Portfolio[]>([])
  const [trades, setTrades] = useState<Trade[]>([])
  const [overview, setOverview] = useState<AgentOverview[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [chartRange, setChartRange] = useState<string>("1W")

  const fetchData = useCallback(async () => {
    try {
      const [statusData, portfoliosData, tradesData, overviewData] = await Promise.all([
        getStatus(),
        getTWPortfolios(),
        getTWTrades(undefined, 20),
        getOverview("tw"),
      ])
      setStatus(statusData)
      setPortfolios(portfoliosData)
      setTrades(tradesData)
      setOverview(overviewData)
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

      {/* Section 2: Agents Now */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold text-foreground">🤖 Agents 現況</h2>
        <AgentOverviewGrid agents={overview} marketPath="/tw" />
      </div>

      {/* Section 3: Equity 走勢圖 */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-foreground">📈 資產走勢（%）</h2>
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
        <EquityChart agents={overview} range={chartRange} />
      </div>

      {/* Section 4: Leaderboard */}
      <Leaderboard
        portfolios={portfolios}
        strategyBasePath="/tw/strategies"
        currencyFormatter={formatCurrencyTW}
      />

      {/* Section 4: Recent Trades */}
      <TradeFeed trades={trades} currencyFormatter={formatCurrencyTWPrecise} />
    </div>
  )
}
