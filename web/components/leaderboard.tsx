"use client"

import Link from "next/link"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { Portfolio } from "@/lib/api"
import { formatCurrency, formatPercent, getRankMedal } from "@/lib/utils"

interface LeaderboardProps {
  portfolios: Portfolio[]
  strategyBasePath?: string
  currencyFormatter?: (value: number) => string
}

export function Leaderboard({
  portfolios,
  strategyBasePath = "/strategies",
  currencyFormatter = formatCurrency,
}: LeaderboardProps) {
  const sorted = [...portfolios].sort(
    (a, b) => b.total_return_pct - a.total_return_pct
  )

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-foreground">Leaderboard</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {sorted.map((portfolio, index) => (
          <LeaderboardCard
            key={portfolio.strategy}
            portfolio={portfolio}
            rank={index + 1}
            strategyBasePath={strategyBasePath}
            currencyFormatter={currencyFormatter}
          />
        ))}
      </div>
    </div>
  )
}

function LeaderboardCard({
  portfolio,
  rank,
  strategyBasePath,
  currencyFormatter,
}: {
  portfolio: Portfolio
  rank: number
  strategyBasePath: string
  currencyFormatter: (value: number) => string
}) {
  const isPositive = portfolio.total_return_pct >= 0

  return (
    <Link href={`${strategyBasePath}/${encodeURIComponent(portfolio.strategy)}`}>
      <Card className="cursor-pointer transition-colors hover:bg-accent/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <span className="text-xl">{getRankMedal(rank)}</span>
            <Badge variant="secondary" className="font-mono text-xs">
              {portfolio.trade_count} trades
            </Badge>
          </div>
          <CardTitle className="text-sm">
            <span className="mr-1.5">{portfolio.emoji}</span>
            {portfolio.strategy}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            <p className="font-mono text-2xl font-bold tabular-nums text-foreground">
              {currencyFormatter(portfolio.total_value)}
            </p>
            <p
              className={`font-mono text-sm font-semibold tabular-nums ${
                isPositive ? "text-green-500" : "text-red-500"
              }`}
            >
              {formatPercent(portfolio.total_return_pct)}
            </p>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
