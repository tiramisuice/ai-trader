"use client"

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-foreground">Settings</h1>

      <Card>
        <CardHeader>
          <CardTitle>API Configuration</CardTitle>
          <CardDescription>
            Backend connection settings for the trading engine
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                API Endpoint
              </p>
              <p className="font-mono text-sm text-foreground">
                {process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}
              </p>
            </div>
            <Separator />
            <p className="text-xs text-muted-foreground">
              To change the API endpoint, edit the{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-foreground">
                .env.local
              </code>{" "}
              file and restart the dev server.
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Dashboard</CardTitle>
          <CardDescription>Display and refresh settings</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-foreground">
                  Auto-refresh
                </p>
                <p className="text-xs text-muted-foreground">
                  Dashboard data refreshes every 30 seconds
                </p>
              </div>
              <span className="rounded-lg bg-green-500/10 px-2 py-1 text-xs font-medium text-green-500">
                Enabled
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>About</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            AI Trader is an AI-powered trading simulator that runs multiple
            strategies against real market data. This dashboard provides
            real-time monitoring and analysis.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
