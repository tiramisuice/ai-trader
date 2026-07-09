"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import type { Status } from "@/lib/api"
import { startTrading, stopTrading, runCycle } from "@/lib/api"
import { cn, formatRelativeTime } from "@/lib/utils"

interface StatusBarProps {
  status: Status | null
  onRefresh: () => void
  runCycleFn?: () => Promise<unknown>
  showToggle?: boolean
  label?: string
}

export function StatusBar({
  status,
  onRefresh,
  runCycleFn,
  showToggle = true,
  label = "Trading",
}: StatusBarProps) {
  const [loading, setLoading] = useState(false)

  async function handleToggle() {
    setLoading(true)
    try {
      if (status?.running) {
        await stopTrading()
      } else {
        await startTrading()
      }
      onRefresh()
    } catch {
      // silently handle error
    } finally {
      setLoading(false)
    }
  }

  async function handleRunNow() {
    setLoading(true)
    try {
      const fn = runCycleFn ?? runCycle
      await fn()
      onRefresh()
    } catch {
      // silently handle error
    } finally {
      setLoading(false)
    }
  }

  const isRunning = status?.running ?? false

  return (
    <div className="flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "inline-block h-2.5 w-2.5 rounded-full",
              isRunning ? "bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]" : "bg-red-500"
            )}
          />
          <span className="text-sm font-medium text-foreground">
            {label}: {isRunning ? "Active" : "Stopped"}
          </span>
        </div>
        {status && (
          <>
            <Badge variant="secondary" className="font-mono text-xs">
              Cycle #{status.cycle_count}
            </Badge>
            {status.last_run && (
              <span className="text-xs text-muted-foreground">
                Last run: {formatRelativeTime(status.last_run)}
              </span>
            )}
            {status.next_run && (
              <span className="text-xs text-muted-foreground">
                Next: {formatRelativeTime(status.next_run)}
              </span>
            )}
          </>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={handleRunNow}
          disabled={loading}
        >
          Run Now
        </Button>
        {showToggle && (
          <Button
            variant={isRunning ? "destructive" : "default"}
            size="sm"
            onClick={handleToggle}
            disabled={loading}
          >
            {isRunning ? "Stop" : "Start"}
          </Button>
        )}
      </div>
    </div>
  )
}

