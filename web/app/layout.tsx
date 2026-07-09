import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import Link from "next/link"
import { MarketNav } from "@/components/market-nav"
import "./globals.css"

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
})

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
})

export const metadata: Metadata = {
  title: "AI Trader",
  description: "AI-powered trading simulator dashboard",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en"
      className={`dark ${geistSans.variable} ${geistMono.variable}`}
    >
      <body className="min-h-screen bg-zinc-950 font-sans text-foreground antialiased">
        <nav className="sticky top-0 z-50 border-b border-border bg-zinc-950/80 backdrop-blur-sm">
          <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
            <Link
              href="/"
              className="flex items-center gap-2 text-lg font-bold tracking-tight text-foreground"
            >
              <span className="text-blue-500">AI</span> TRADER
            </Link>
            <div className="flex items-center gap-6">
              <MarketNav />
              <Link
                href="/history"
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                History
              </Link>
              <Link
                href="/settings"
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                Settings
              </Link>
            </div>
          </div>
        </nav>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </body>
    </html>
  )
}
