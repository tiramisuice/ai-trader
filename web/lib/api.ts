const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface Position {
  ticker: string;
  shares: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
}

export interface Portfolio {
  strategy: string;
  emoji: string;
  description: string;
  model: string;
  cash: number;
  positions: Position[];
  total_value: number;
  initial_capital: number;
  total_return: number;
  total_return_pct: number;
  trade_count: number;
}

export interface Trade {
  id: string;
  timestamp: string;
  strategy: string;
  emoji: string;
  action: "BUY" | "SELL";
  ticker: string;
  shares: number;
  price: number;
  reason: string;
}

export interface Strategy {
  name: string;
  emoji: string;
  description: string;
  model: string;
  rules_summary: string;
  watchlist: string[] | null;
}

export interface PositionDetail {
  ticker: string;
  shares: number;
  avg_cost: number;
  current_price: number;
  unrealized_pnl: number;
  pnl_pct: number;
  day_change_pct: number;
  chart_data: { date: string; close: number }[];
}

export interface PositionsResponse {
  strategy: string;
  positions: PositionDetail[];
}

export interface Status {
  running: boolean;
  cycle_count: number;
  next_run: string | null;
  last_run: string | null;
}

export interface Snapshot {
  timestamp: string;
  total_value: number;
  cash: number;
  positions_value: number;
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }

  return res.json() as Promise<T>;
}

/** Normalize a raw API portfolio: convert positions dict→array, fill missing fields */
function normalizePortfolio(raw: Record<string, unknown>): Portfolio {
  const p = raw as Record<string, unknown>;

  // positions can be a dict {ticker: {...}} or array — normalize to array
  let positions: Position[] = [];
  if (p.positions && !Array.isArray(p.positions)) {
    positions = Object.values(p.positions as Record<string, Record<string, unknown>>).map((pos) => ({
      ticker: (pos.ticker as string) ?? "",
      shares: (pos.shares as number) ?? 0,
      avg_cost: (pos.avg_cost as number) ?? 0,
      current_price: (pos.current_price as number) ?? 0,
      market_value: (pos.market_value as number) ?? (pos.shares as number ?? 0) * (pos.current_price as number ?? 0),
      unrealized_pnl: (pos.unrealized_pnl as number) ?? ((pos.current_price as number ?? 0) - (pos.avg_cost as number ?? 0)) * (pos.shares as number ?? 0),
      unrealized_pnl_pct: (pos.unrealized_pnl_pct as number) ?? ((pos.avg_cost as number) ? (((pos.current_price as number ?? 0) - (pos.avg_cost as number)) / (pos.avg_cost as number)) * 100 : 0),
    }));
  } else if (Array.isArray(p.positions)) {
    positions = p.positions;
  }

  const cash = (p.cash as number) ?? 0;
  const initialCapital = (p.initial_capital as number) ?? ((p.market as string) === "tw" ? 300000 : 10000);
  const totalValue = (p.total_value as number) ?? 0;

  return {
    strategy: (p.strategy as string) ?? "",
    emoji: (p.emoji as string) ?? "",
    description: (p.description as string) ?? "",
    model: (p.model as string) ?? "",
    cash,
    positions,
    total_value: totalValue,
    initial_capital: initialCapital,
    total_return: (p.total_return as number) ?? totalValue - initialCapital,
    total_return_pct: (p.total_return_pct as number) ?? 0,
    trade_count: (p.trade_count as number) ?? 0,
  };
}

export async function getPortfolios(): Promise<Portfolio[]> {
  const raw = await apiFetch<Record<string, unknown>[]>("/api/portfolios");
  return raw.map(normalizePortfolio);
}

export async function getPortfolio(strategy: string): Promise<Portfolio> {
  const raw = await apiFetch<Record<string, unknown>>(`/api/portfolios/${encodeURIComponent(strategy)}`);
  return normalizePortfolio(raw);
}

export async function getTrades(
  strategy?: string,
  limit?: number
): Promise<Trade[]> {
  const params = new URLSearchParams();
  if (strategy) params.set("strategy", strategy);
  if (limit) params.set("limit", String(limit));
  const query = params.toString();
  return apiFetch<Trade[]>(`/api/trades${query ? `?${query}` : ""}`);
}

export async function getStrategies(): Promise<Strategy[]> {
  return apiFetch<Strategy[]>("/api/strategies");
}

export async function getStatus(): Promise<Status> {
  return apiFetch<Status>("/api/status");
}

export async function getSnapshots(strategy: string): Promise<Snapshot[]> {
  return apiFetch<Snapshot[]>(
    `/api/snapshots/${encodeURIComponent(strategy)}`
  );
}

export async function getPositionsDetail(
  strategy: string
): Promise<PositionsResponse> {
  return apiFetch<PositionsResponse>(
    `/api/portfolios/${encodeURIComponent(strategy)}/positions`
  );
}

// --- Taiwan (台股) endpoints ---

export async function getTWPortfolios(): Promise<Portfolio[]> {
  const raw = await apiFetch<Record<string, unknown>[]>("/api/portfolios/tw");
  return raw.map(normalizePortfolio);
}

export async function getTWPortfolio(strategy: string): Promise<Portfolio> {
  const raw = await apiFetch<Record<string, unknown>>(
    `/api/portfolios/tw/${encodeURIComponent(strategy)}`
  );
  return normalizePortfolio(raw);
}

export async function getTWTrades(
  strategy?: string,
  limit?: number
): Promise<Trade[]> {
  const params = new URLSearchParams();
  if (strategy) params.set("strategy", strategy);
  if (limit) params.set("limit", String(limit));
  params.set("market", "tw");
  const query = params.toString();
  return apiFetch<Trade[]>(`/api/trades${query ? `?${query}` : ""}`);
}

export async function getTWStrategies(): Promise<Strategy[]> {
  return apiFetch<Strategy[]>("/api/strategies/tw");
}

export async function getTWPositionsDetail(
  strategy: string
): Promise<PositionsResponse> {
  return apiFetch<PositionsResponse>(
    `/api/portfolios/tw/${encodeURIComponent(strategy)}/positions`
  );
}

// --- Decision Flow types ---

export interface DecisionFlow {
  strategy: string
  cycle_number: number
  timestamp: string
  pipeline: {
    regime: {
      current: string
      probabilities: Record<string, number>
      position_scale: number
      description: string
    } | null
    top_signals: Array<{
      ticker: string
      combined_score: number
      signal: string
      rank: number
      breakdown: { technical: number; factor: number; insider: number }
      suggested_weight: number
      confidence: number
    }>
    anomalies: Array<{
      ticker: string
      type: string
      severity: string
      message: string
    }>
    earnings: Array<{
      ticker: string
      sentiment: string
      guidance: string
    }>
    tickers_scanned: number
  }
  llm_input: {
    market_data_preview: string
    news_preview: string
    wake_reason?: string // soul era (season 2+)
  }
  llm_output: {
    market_analysis: string
    reasoning: string
    orders_proposed: Array<{
      action: string
      ticker: string
      shares: number
      reason: string
    }>
    // soul era (season 2+)
    journal?: string
    conditional_orders?: Array<{
      action: string
      ticker: string
      shares: number
      trigger: string
      trigger_price: number
      good_for_days: number
      reason: string
    }>
    wake_triggers?: Array<{ ticker: string; condition: string; price: number }>
    next_check_hours?: number
  }
  risk_check: {
    // cage era (season 1) — absent in soul-era logs
    orders_approved?: Array<{
      action: string
      ticker: string
      shares: number
      original_shares: number
      adjustments: string[]
    }>
    orders_blocked?: Array<{
      action: string
      ticker: string
      shares: number
      reason: string
    }>
    // soul era (season 2+): physics rejections only
    orders_rejected?: Array<{
      order: { action: string; ticker: string; shares: number; reason: string }
      why: string
    }>
  }
  execution: {
    trades_executed: Array<Record<string, unknown>>
    portfolio_after: {
      cash: number
      total_value: number
      return_pct: number
    }
  }
}

export async function getDecisionFlow(strategy: string): Promise<DecisionFlow | null> {
  try {
    return await apiFetch<DecisionFlow>(`/api/decision/${encodeURIComponent(strategy)}`)
  } catch {
    return null
  }
}

// --- Market hours helper ---

export function getActiveMarket(): "us" | "tw" | "closed" {
  const now = new Date();
  // Taiwan time = UTC+8
  const twHour = (now.getUTCHours() + 8) % 24;
  const twMinute = now.getUTCMinutes();
  // Day of week in UTC — adjust for Taiwan timezone
  const twDate = new Date(now.getTime() + 8 * 60 * 60 * 1000);
  const twDay = twDate.getUTCDay(); // 0=Sun, 6=Sat

  // Weekend check (in Taiwan time)
  const twWeekday = twDay >= 1 && twDay <= 5;

  // Taiwan market: 9:00-13:30 Taiwan time
  const twOpen =
    twWeekday &&
    (twHour > 9 || (twHour === 9 && twMinute >= 0)) &&
    (twHour < 13 || (twHour === 13 && twMinute <= 30));

  // US market: 9:30-16:00 ET (= UTC-4 during EDT)
  const etOffset = -4; // EDT; change to -5 for EST
  const etDate = new Date(now.getTime() + etOffset * 60 * 60 * 1000);
  const etDay = etDate.getUTCDay();
  const etHour = etDate.getUTCHours();
  const etMinute = etDate.getUTCMinutes();
  const usWeekday = etDay >= 1 && etDay <= 5;
  const usOpen =
    usWeekday &&
    (etHour > 9 || (etHour === 9 && etMinute >= 30)) &&
    etHour < 16;

  if (twOpen) return "tw";
  if (usOpen) return "us";
  return "closed";
}

// --- Soul-era: agent overview + stock detail ---

export interface AgentOverview {
  strategy: string
  display_name: string
  emoji: string
  model: string
  style: string
  currency: string
  total_value: number
  return_pct: number
  cash: number
  positions: Array<{ ticker: string; shares: number; pnl_pct: number }>
  next_wakeup: string | null
  watchlist_size: number
  intents: Array<{
    kind: string
    action: string | null
    ticker: string
    shares: number | null
    trigger_type: string
    trigger_price: number
    reason: string
    expires_at: string
  }>
  last_journal: { timestamp: string; wake_reason: string; entry: string } | null
  sparkline: Array<{ t: string; v: number }>
}

export async function getOverview(market: "us" | "tw" = "us"): Promise<AgentOverview[]> {
  return apiFetch<AgentOverview[]>(`/api/overview?market=${market}`)
}

export interface StockDetail {
  ticker: string
  name: string
  quote: {
    price: number
    day_change_pct: number
    volume: number | null
    market_cap: number | null
    pe_ratio: number | null
    dividend_yield: number | null
  }
  stats: {
    high_52w: number
    low_52w: number
    sma20: number | null
    sma50: number | null
    rsi14: number | null
    return_range_pct: number
  }
  chart: Array<{ date: string; close: number }>
  holders: Array<{
    strategy: string
    display_name: string
    emoji: string
    market: string
    shares: number
    avg_cost: number
    pnl_pct: number
  }>
  recent_trades: Trade[]
  intents: Array<{
    strategy: string
    kind: string
    action: string | null
    shares: number | null
    trigger_type: string
    trigger_price: number
    reason: string
  }>
}

export type StockRange = "1mo" | "3mo" | "6mo" | "1y" | "2y"

export async function getStockDetail(ticker: string, range: StockRange = "6mo"): Promise<StockDetail> {
  return apiFetch<StockDetail>(`/api/stock/${encodeURIComponent(ticker)}?range=${range}`)
}

// Fixed per-agent colors (colorblind-safe on dark, validated)
export const AGENT_COLORS: Record<string, string> = {
  buffett: "#d97706", ark: "#a855f7", aggressive: "#f43f5e",
  balanced: "#0d9488", quant: "#3b82f6",
  tw_buffett: "#d97706", tw_ark: "#a855f7", tw_aggressive: "#f43f5e",
  tw_balanced: "#0d9488", tw_quant: "#3b82f6",
}
