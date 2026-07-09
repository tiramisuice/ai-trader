"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { getActiveMarket } from "@/lib/api"

export function MarketNav() {
  const pathname = usePathname()
  const [activeMarket, setActiveMarket] = useState<"us" | "tw" | "closed">(
    "closed"
  )

  useEffect(() => {
    setActiveMarket(getActiveMarket())
    // Re-check every minute
    const interval = setInterval(() => {
      setActiveMarket(getActiveMarket())
    }, 60_000)
    return () => clearInterval(interval)
  }, [])

  const isUSPage = pathname === "/" || pathname.startsWith("/strategies")
  const isTWPage = pathname.startsWith("/tw")

  const usIndicator = activeMarket === "us" ? "\u{1F7E2}" : "\u26AB"
  const twIndicator = activeMarket === "tw" ? "\u{1F7E2}" : "\u26AB"
  const usFlag = "\u{1F1FA}\u{1F1F8}"
  const twFlag = "\u{1F1F9}\u{1F1FC}"

  return (
    <div className="flex items-center gap-1 rounded-lg border border-border bg-zinc-900 p-0.5">
      <Link
        href="/"
        className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
          isUSPage
            ? "bg-zinc-800 text-foreground"
            : "text-muted-foreground hover:text-foreground"
        }`}
      >
        <span className="text-xs">{usIndicator}</span>
        <span>{usFlag} US</span>
      </Link>
      <Link
        href="/tw"
        className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
          isTWPage
            ? "bg-zinc-800 text-foreground"
            : "text-muted-foreground hover:text-foreground"
        }`}
      >
        <span className="text-xs">{twIndicator}</span>
        <span>{twFlag} {"\u53F0\u80A1"}</span>
      </Link>
    </div>
  )
}
