import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value)
}

export function formatCurrencyPrecise(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

export function formatCurrencyTW(value: number): string {
  return `NT$${(value ?? 0).toLocaleString("zh-TW", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

export function formatCurrencyTWPrecise(value: number): string {
  return `NT$${(value ?? 0).toLocaleString("zh-TW", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function formatPercent(value: number): string {
  const v = value ?? 0
  const sign = v >= 0 ? "+" : ""
  return `${sign}${v.toFixed(2)}%`
}

export function formatRelativeTime(timestamp: string): string {
  const now = new Date()
  const then = new Date(timestamp)
  const diffMs = now.getTime() - then.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffSec < 60) return `${diffSec}s ago`
  if (diffMin < 60) return `${diffMin} min ago`
  if (diffHour < 24) return `${diffHour}h ago`
  return `${diffDay}d ago`
}

export function getRankMedal(rank: number): string {
  switch (rank) {
    case 1:
      return "🏆"
    case 2:
      return "🥈"
    case 3:
      return "🥉"
    default:
      return `#${rank}`
  }
}
