"use client"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import type { Status } from "@/lib/api"
import { cn, formatRelativeTime } from "@/lib/utils"

interface StatusBarProps {
  status: Status | null
  onRefresh: () => void
  label?: string
}

export function StatusBar({
  status,
  onRefresh,
  label = "Trading",
}: StatusBarProps) {
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
      {/* Read-only: start/stop/manual cycles require the admin token (see README) */}
      <Button variant="outline" size="sm" onClick={onRefresh}>
        Refresh
      </Button>
    </div>
  )
}

