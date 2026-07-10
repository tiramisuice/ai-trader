"use client"

import Link from "next/link"

import { useState } from "react"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import type { Trade } from "@/lib/api"
import { formatCurrencyPrecise, formatRelativeTime } from "@/lib/utils"
import { getStockName } from "@/lib/stock-names"

interface TradeFeedProps {
  trades: Trade[]
  currencyFormatter?: (value: number) => string
}

export function TradeFeed({ trades, currencyFormatter }: TradeFeedProps) {
  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-foreground">Recent Trades</h2>
      <div className="rounded-xl border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="border-border hover:bg-transparent">
              <TableHead>Time</TableHead>
              <TableHead>Strategy</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Ticker</TableHead>
              <TableHead className="text-right">Shares</TableHead>
              <TableHead className="text-right">Price</TableHead>
              <TableHead>Reason</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {trades.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="py-8 text-center text-muted-foreground"
                >
                  No trades yet
                </TableCell>
              </TableRow>
            ) : (
              trades.map((trade) => (
                <TradeRow key={trade.id} trade={trade} currencyFormatter={currencyFormatter} />
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function TradeRow({ trade, currencyFormatter }: { trade: Trade; currencyFormatter?: (value: number) => string }) {
  const [expanded, setExpanded] = useState(false)
  const isBuy = trade.action === "BUY"
  const fmtPrice = currencyFormatter ?? formatCurrencyPrecise

  return (
    <TableRow className="border-border">
      <TableCell className="font-mono text-xs text-muted-foreground">
        {formatRelativeTime(trade.timestamp)}
      </TableCell>
      <TableCell>
        <span className="mr-1">{trade.emoji}</span>
        <span className="text-sm">{trade.strategy}</span>
      </TableCell>
      <TableCell>
        <Badge
          variant="secondary"
          className={
            isBuy
              ? "bg-green-500/10 text-green-500"
              : "bg-red-500/10 text-red-500"
          }
        >
          {trade.action}
        </Badge>
      </TableCell>
      <TableCell>
        <Link href={`/stock/${trade.ticker}`} className="font-mono font-semibold hover:underline">{trade.ticker}</Link>
        {getStockName(trade.ticker) && (
          <span className="ml-1.5 text-xs text-muted-foreground">{getStockName(trade.ticker)}</span>
        )}
      </TableCell>
      <TableCell className="text-right font-mono tabular-nums">
        {trade.shares}
      </TableCell>
      <TableCell className="text-right font-mono tabular-nums">
        {fmtPrice(trade.price)}
      </TableCell>
      <TableCell className="max-w-[200px]">
        <button
          onClick={() => setExpanded(!expanded)}
          className="cursor-pointer text-left text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          {expanded ? trade.reason : truncate(trade.reason, 40)}
        </button>
      </TableCell>
    </TableRow>
  )
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text
  return text.slice(0, maxLen) + "..."
}
