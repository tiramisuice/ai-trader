"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { getActiveMarket } from "@/lib/api"

export function MarketBanner() {
  const [activeMarket, setActiveMarket] = useState<"us" | "tw" | "closed">(
    "closed"
  )

  useEffect(() => {
    setActiveMarket(getActiveMarket())
    const interval = setInterval(() => {
      setActiveMarket(getActiveMarket())
    }, 60_000)
    return () => clearInterval(interval)
  }, [])

  if (activeMarket !== "tw") return null

  return (
    <div className="flex items-center justify-between rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-2">
      <div className="flex items-center gap-3 text-sm">
        <span>
          {"\u{1F1F9}\u{1F1FC}"} &#x53F0;&#x80A1; OPEN
        </span>
        <span className="text-muted-foreground">|</span>
        <span className="text-muted-foreground">
          {"\u{1F1FA}\u{1F1F8}"} US Closed
        </span>
      </div>
      <Link
        href="/tw"
        className="text-sm font-medium text-amber-500 transition-colors hover:text-amber-400"
      >
        &#x5207;&#x63DB;&#x53F0;&#x80A1; &rarr;
      </Link>
    </div>
  )
}
