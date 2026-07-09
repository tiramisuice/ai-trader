"use client"

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts"

interface ChartDataPoint {
  date: string
  close: number
}

interface PositionChartProps {
  data: ChartDataPoint[]
  currencyPrefix?: string
}

function CustomTooltip({
  active,
  payload,
  label,
  currencyPrefix = "$",
}: {
  active?: boolean
  payload?: { value: number }[]
  label?: string
  currencyPrefix?: string
}) {
  if (!active || !payload?.length) return null

  return (
    <div className="rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-xs shadow-lg">
      <p className="text-zinc-400">{label}</p>
      <p className="font-mono font-semibold tabular-nums text-zinc-100">
        {currencyPrefix}{payload[0].value.toFixed(2)}
      </p>
    </div>
  )
}

export function PositionChart({ data, currencyPrefix = "$" }: PositionChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-[160px] items-center justify-center text-xs text-zinc-500">
        No chart data
      </div>
    )
  }

  const prices = data.map((d) => d.close)
  const minPrice = Math.min(...prices)
  const maxPrice = Math.max(...prices)
  const padding = (maxPrice - minPrice) * 0.1 || 1

  return (
    <div className="h-[160px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={data}
          margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
        >
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: "#71717a" }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
            tickFormatter={(value: string) => {
              const parts = value.split("-")
              return `${parts[1]}/${parts[2]}`
            }}
          />
          <YAxis
            domain={[minPrice - padding, maxPrice + padding]}
            tick={{ fontSize: 10, fill: "#71717a" }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value: number) => `${currencyPrefix}${value.toFixed(0)}`}
            width={55}
          />
          <Tooltip content={<CustomTooltip currencyPrefix={currencyPrefix} />} />
          <Line
            type="monotone"
            dataKey="close"
            stroke="#60a5fa"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 3, fill: "#60a5fa" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
