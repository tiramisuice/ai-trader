"use client"

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { Portfolio } from "@/lib/api"
import {
  formatCurrency,
  formatCurrencyPrecise,
  formatPercent,
} from "@/lib/utils"
import { getStockName } from "@/lib/stock-names"

interface StrategyCardProps {
  portfolio: Portfolio
}

export function StrategyCard({ portfolio }: StrategyCardProps) {
  return (
    <div className="space-y-4">
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
              value={formatCurrency(portfolio.total_value)}
            />
            <MetricBlock
              label="Cash"
              value={formatCurrency(portfolio.cash)}
            />
            <MetricBlock
              label="Total P&L"
              value={formatCurrency(portfolio.total_return)}
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

      {portfolio.positions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Positions</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead>Ticker</TableHead>
                  <TableHead className="text-right">Shares</TableHead>
                  <TableHead className="text-right">Avg Cost</TableHead>
                  <TableHead className="text-right">Current</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                  <TableHead className="text-right">P&L</TableHead>
                  <TableHead className="text-right">P&L %</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {portfolio.positions.map((pos) => (
                  <TableRow key={pos.ticker} className="border-border">
                    <TableCell>
                      <span className="font-mono font-semibold">{pos.ticker}</span>
                      {getStockName(pos.ticker) && (
                        <span className="ml-1.5 text-xs text-muted-foreground">{getStockName(pos.ticker)}</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {pos.shares}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatCurrencyPrecise(pos.avg_cost)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatCurrencyPrecise(pos.current_price)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatCurrency(pos.market_value)}
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono tabular-nums ${
                        pos.unrealized_pnl >= 0
                          ? "text-green-500"
                          : "text-red-500"
                      }`}
                    >
                      {formatCurrencyPrecise(pos.unrealized_pnl)}
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono tabular-nums ${
                        pos.unrealized_pnl_pct >= 0
                          ? "text-green-500"
                          : "text-red-500"
                      }`}
                    >
                      {formatPercent(pos.unrealized_pnl_pct)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
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
