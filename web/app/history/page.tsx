"use client"

import { useEffect, useState, useCallback } from "react"
import { TradeFeed } from "@/components/trade-feed"
import { TradeFeedSkeleton } from "@/components/dashboard-skeletons"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import type { Trade, Strategy } from "@/lib/api"
import { getTrades, getStrategies } from "@/lib/api"

export default function HistoryPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [selectedStrategy, setSelectedStrategy] = useState<string>("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const [tradesData, strategiesData] = await Promise.all([
        getTrades(selectedStrategy || undefined, 100),
        getStrategies(),
      ])
      setTrades(tradesData)
      setStrategies(strategiesData)
      setError(null)
    } catch {
      setError("Failed to load trade history.")
    } finally {
      setLoading(false)
    }
  }, [selectedStrategy])

  useEffect(() => {
    setLoading(true)
    fetchData()
  }, [fetchData])

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Card className="max-w-md">
          <CardContent className="pt-6 text-center">
            <p className="mb-2 text-4xl">🔌</p>
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
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground">Trade History</h1>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Strategy:</span>
          <select
            value={selectedStrategy}
            onChange={(e) => setSelectedStrategy(e.target.value)}
            className="h-8 rounded-lg border border-border bg-card px-3 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/50"
          >
            <option value="">All Strategies</option>
            {strategies.map((s) => (
              <option key={s.name} value={s.name}>
                {s.emoji} {s.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading ? <TradeFeedSkeleton /> : <TradeFeed trades={trades} />}
    </div>
  )
}
