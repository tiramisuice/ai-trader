"use client"

import { useEffect, useState, useCallback, use } from "react"
import Link from "next/link"
import { StrategyCard } from "@/components/strategy-card"
import { TradeFeed } from "@/components/trade-feed"
import dynamic from "next/dynamic"
const PositionChart = dynamic(() => import("@/components/position-chart").then(m => m.PositionChart), { ssr: false })
const DecisionFlowComponent = dynamic(() => import("@/components/decision-flow").then(m => m.DecisionFlowComponent), { ssr: false })
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import type {
  Portfolio,
  Trade,
  Strategy,
  PositionDetail,
  DecisionFlow,
} from "@/lib/api"
import {
  getTWPortfolio,
  getTWTrades,
  getTWStrategies,
  getTWPositionsDetail,
  getDecisionFlow,
} from "@/lib/api"
import {
  formatCurrencyTW,
  formatCurrencyTWPrecise,
  formatPercent,
} from "@/lib/utils"
import { getStockName } from "@/lib/stock-names"

export default function TWStrategyDetailPage({
  params,
}: {
  params: Promise<{ name: string }>
}) {
  const { name } = use(params)
  const strategyName = decodeURIComponent(name)

  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [strategy, setStrategy] = useState<Strategy | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])
  const [positions, setPositions] = useState<PositionDetail[]>([])
  const [decisionFlow, setDecisionFlow] = useState<DecisionFlow | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showWatchlist, setShowWatchlist] = useState(false)

  const fetchData = useCallback(async () => {
    try {
      const [portfolioData, tradesData, strategiesData] = await Promise.all([
        getTWPortfolio(strategyName),
        getTWTrades(strategyName),
        getTWStrategies(),
      ])
      setPortfolio(portfolioData)
      setTrades(tradesData)
      const found = strategiesData.find((s) => s.name === strategyName)
      if (found) setStrategy(found)

      // Try fetching detailed positions; fall back silently
      try {
        const posData = await getTWPositionsDetail(strategyName)
        setPositions(posData.positions)
      } catch {
        // positions endpoint not available — use empty array
        setPositions([])
      }

      // Try fetching decision flow; non-blocking
      try {
        const flowData = await getDecisionFlow(strategyName)
        setDecisionFlow(flowData)
      } catch {
        setDecisionFlow(null)
      }

      setError(null)
    } catch {
      setError("Failed to load strategy data.")
    } finally {
      setLoading(false)
    }
  }, [strategyName])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-72 w-full" />
        </div>
      </div>
    )
  }

  if (error || !portfolio) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Card className="max-w-md">
          <CardContent className="pt-6 text-center">
            <p className="mb-2 text-4xl">&#x274C;</p>
            <h2 className="mb-2 text-lg font-semibold text-foreground">
              Strategy Not Found
            </h2>
            <p className="mb-4 text-sm text-muted-foreground">
              {error || `Could not find strategy "${strategyName}"`}
            </p>
            <Link href="/tw">
              <Button variant="outline">Back to Dashboard</Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    )
  }

  const lastTrade = trades.length > 0 ? trades[0] : null
  const watchlist = strategy?.watchlist ?? null
  const sortedPositions = [...positions].sort(
    (a, b) => Math.abs(b.unrealized_pnl) - Math.abs(a.unrealized_pnl)
  )

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Link href="/tw" className="transition-colors hover:text-foreground">
          &#x53F0;&#x80A1; Dashboard
        </Link>
        <span>/</span>
        <span className="text-foreground">
          {portfolio.emoji} {strategyName}
        </span>
      </div>

      {/* Strategy Info */}
      {strategy && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-3">
              <span className="text-3xl">{strategy.emoji}</span>
              <div>
                <CardTitle className="text-xl">{strategy.name}</CardTitle>
                <CardDescription>{strategy.description}</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-3">
              <Badge variant="secondary">Model: {strategy.model}</Badge>
              <Badge variant="outline">{portfolio.trade_count} trades</Badge>
              {watchlist ? (
                <Badge variant="secondary">
                  Watchlist: {watchlist.length} stocks
                </Badge>
              ) : (
                <Badge variant="outline">Free Market</Badge>
              )}
            </div>

            {/* Watchlist expand/collapse */}
            {watchlist && watchlist.length > 0 && (
              <div className="mt-3">
                <button
                  onClick={() => setShowWatchlist(!showWatchlist)}
                  className="text-xs text-muted-foreground transition-colors hover:text-foreground"
                >
                  {showWatchlist
                    ? "Hide watchlist"
                    : `Show ${watchlist.length} watchlist tickers`}
                </button>
                {showWatchlist && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {watchlist.map((ticker) => (
                      <Badge
                        key={ticker}
                        variant="outline"
                        className="font-mono text-xs"
                      >
                        {ticker}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            )}

            {strategy.rules_summary && (
              <>
                <Separator className="my-4" />
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">
                    Rules Summary
                  </p>
                  <p className="text-sm text-foreground">
                    {strategy.rules_summary}
                  </p>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {/* Cash & Summary */}
      <Card>
        <CardHeader>
          <CardTitle>Portfolio Overview</CardTitle>
          <CardDescription>
            Current holdings and cash balance
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <MetricBlock
              label="Total Value"
              value={formatCurrencyTW(portfolio.total_value)}
            />
            <MetricBlock
              label="Cash"
              value={formatCurrencyTW(portfolio.cash)}
            />
            <MetricBlock
              label="Total P&L"
              value={formatCurrencyTW(portfolio.total_return)}
              color={portfolio.total_return >= 0 ? "green" : "red"}
            />
            <MetricBlock
              label="Return"
              value={formatPercent(portfolio.total_return_pct)}
              color={portfolio.total_return_pct >= 0 ? "green" : "red"}
            />
          </div>
        </CardContent>
      </Card>

      {/* Decision Flow */}
      <div className="space-y-2">
        <h2 className="text-lg font-semibold text-foreground">Decision Flow</h2>
        <p className="text-sm text-muted-foreground">
          Last trading cycle analysis
        </p>
        <DecisionFlowComponent data={decisionFlow} />
      </div>

      {/* Detailed Positions */}
      {sortedPositions.length > 0 ? (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold text-foreground">
            Positions ({sortedPositions.length})
          </h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {sortedPositions.map((pos) => (
              <PositionCard key={pos.ticker} position={pos} />
            ))}
          </div>
        </div>
      ) : portfolio.positions.length > 0 ? (
        /* Fall back to basic positions table if detailed positions not available */
        <StrategyCard portfolio={portfolio} />
      ) : (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            No positions yet &mdash; all cash
          </CardContent>
        </Card>
      )}

      {/* AI's Last Reasoning */}
      {lastTrade && lastTrade.reason && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Last AI Reasoning</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2 mb-2 text-xs text-muted-foreground">
              <Badge
                variant="secondary"
                className={
                  lastTrade.action === "BUY"
                    ? "bg-green-500/10 text-green-500"
                    : "bg-red-500/10 text-red-500"
                }
              >
                {lastTrade.action}
              </Badge>
              <span className="font-mono font-semibold text-foreground">
                {lastTrade.ticker}
              </span>
              <span>&middot;</span>
              <span>
                {lastTrade.shares} shares @ {formatCurrencyTWPrecise(lastTrade.price)}
              </span>
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">
              {lastTrade.reason}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Trade History */}
      <TradeFeed trades={trades} currencyFormatter={formatCurrencyTWPrecise} />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function PositionCard({ position }: { position: PositionDetail }) {
  const pnlColor =
    position.unrealized_pnl >= 0 ? "text-green-500" : "text-red-500"
  const dayColor =
    position.day_change_pct >= 0 ? "text-green-500" : "text-red-500"
  const stockName = getStockName(position.ticker)

  return (
    <Card>
      <CardContent className="space-y-3 pt-4">
        {/* Top row: ticker, shares, current price */}
        <div className="flex items-baseline justify-between">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-lg font-bold text-foreground">
              {position.ticker}
            </span>
            {stockName && (
              <span className="text-sm text-muted-foreground">{stockName}</span>
            )}
          </div>
          <div className="flex items-baseline gap-4 text-sm">
            <span className="text-muted-foreground">
              {position.shares} shares
            </span>
            <span className="font-mono font-semibold tabular-nums text-foreground">
              {formatCurrencyTWPrecise(position.current_price)}
            </span>
          </div>
        </div>

        {/* Second row: avg cost, P&L, day change */}
        <div className="grid grid-cols-4 gap-2 text-xs">
          <div>
            <p className="text-muted-foreground">Avg Cost</p>
            <p className="font-mono tabular-nums text-foreground">
              {formatCurrencyTWPrecise(position.avg_cost)}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">P&amp;L</p>
            <p className={`font-mono tabular-nums ${pnlColor}`}>
              {formatCurrencyTWPrecise(position.unrealized_pnl)}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">P&amp;L %</p>
            <p className={`font-mono tabular-nums ${pnlColor}`}>
              {formatPercent(position.pnl_pct)}
            </p>
          </div>
          <div>
            <p className="text-muted-foreground">Day</p>
            <p className={`font-mono tabular-nums ${dayColor}`}>
              {formatPercent(position.day_change_pct)}
            </p>
          </div>
        </div>

        {/* Chart */}
        <PositionChart data={position.chart_data} currencyPrefix="NT$" />
      </CardContent>
    </Card>
  )
}

function MetricBlock({
  label,
  value,
  color,
}: {
  label: string
  value: string
  color?: "green" | "red"
}) {
  const colorClass =
    color === "green"
      ? "text-green-500"
      : color === "red"
        ? "text-red-500"
        : "text-foreground"

  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`font-mono text-xl font-bold tabular-nums ${colorClass}`}>
        {value}
      </p>
    </div>
  )
}
