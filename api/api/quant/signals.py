"""Quantitative signal engine — pure math, no LLM."""

from __future__ import annotations
import logging
import numpy as np
from dataclasses import dataclass
from typing import Literal

from api.data.fetch import fetch_history as _fetch_history

logger = logging.getLogger(__name__)

@dataclass
class TechnicalSignals:
    """Computed technical indicators for a single stock."""
    ticker: str
    price: float

    # Moving averages
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    price_vs_sma20: str  # "above" or "below"
    price_vs_sma50: str
    price_vs_sma200: str
    golden_cross: bool  # SMA50 > SMA200
    death_cross: bool   # SMA50 < SMA200

    # RSI
    rsi_14: float | None
    rsi_signal: str  # "oversold", "overbought", "neutral"

    # MACD
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    macd_crossover: str  # "bullish", "bearish", "neutral"

    # Bollinger Bands
    bb_upper: float | None
    bb_lower: float | None
    bb_position: str  # "above_upper", "below_lower", "inside"

    # Volume
    volume: int
    avg_volume_20: float | None
    volume_ratio: float | None  # current / average
    high_volume: bool

    # Volatility
    atr_14: float | None  # Average True Range
    daily_volatility: float | None  # Standard deviation of returns

    # Overall score
    score: int  # -10 to +10
    signal: str  # "strong_buy", "buy", "neutral", "sell", "strong_sell"

def compute_signals(ticker: str, hist=None) -> TechnicalSignals | None:
    """Compute all technical signals for a ticker. Returns None on failure.

    Pass `hist` (an OHLCV frame from the batch downloader) to avoid a
    per-ticker network fetch."""
    try:
        if hist is None:
            hist = _fetch_history(ticker, "1y")  # Need 200+ days for SMA200
        if hist.empty or len(hist) < 20:
            return None

        close = hist["Close"]
        high = hist["High"]
        low = hist["Low"]
        volume = hist["Volume"]
        price = float(close.iloc[-1])

        # --- Moving Averages ---
        sma_20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else None
        sma_50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        sma_200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

        # --- RSI (14-period) ---
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        rsi_14 = float(rsi_series.iloc[-1]) if len(rsi_series) >= 14 else None
        if rsi_14 is not None and np.isnan(rsi_14):
            # 0/0 on a flat series, or too few data points in the window
            rsi_14 = None

        # --- MACD ---
        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema_12 - ema_26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line
        macd_val = float(macd_line.iloc[-1]) if len(macd_line) >= 26 else None
        macd_sig = float(signal_line.iloc[-1]) if len(signal_line) >= 26 else None
        macd_hist = float(histogram.iloc[-1]) if len(histogram) >= 26 else None

        # MACD crossover detection
        macd_crossover = "neutral"
        if macd_val is not None and macd_sig is not None and len(macd_line) >= 27:
            prev_diff = float(macd_line.iloc[-2] - signal_line.iloc[-2])
            curr_diff = macd_val - macd_sig
            if prev_diff < 0 and curr_diff > 0:
                macd_crossover = "bullish"
            elif prev_diff > 0 and curr_diff < 0:
                macd_crossover = "bearish"

        # --- Bollinger Bands (20-period, 2 std) ---
        bb_mid = sma_20
        bb_std = float(close.rolling(20).std().iloc[-1]) if len(close) >= 20 else None
        bb_upper = bb_mid + 2 * bb_std if bb_mid and bb_std else None
        bb_lower = bb_mid - 2 * bb_std if bb_mid and bb_std else None

        bb_position = "inside"
        if bb_upper and price > bb_upper:
            bb_position = "above_upper"
        elif bb_lower and price < bb_lower:
            bb_position = "below_lower"

        # --- Volume ---
        curr_vol = int(volume.iloc[-1])
        avg_vol_20 = float(volume.rolling(20).mean().iloc[-1]) if len(volume) >= 20 else None
        vol_ratio = curr_vol / avg_vol_20 if avg_vol_20 and avg_vol_20 > 0 else None

        # --- ATR (14-period) ---
        tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
        atr_14 = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else None

        # --- Daily Volatility ---
        returns = close.pct_change().dropna()
        daily_vol = float(returns.tail(20).std()) if len(returns) >= 20 else None

        # --- Scoring System ---
        score = 0

        # RSI scoring
        if rsi_14 is not None:
            if rsi_14 < 30: score += 2    # Oversold = buy signal
            elif rsi_14 < 40: score += 1
            elif rsi_14 > 70: score -= 2  # Overbought = sell signal
            elif rsi_14 > 60: score -= 1

        # MACD scoring
        if macd_crossover == "bullish": score += 2
        elif macd_crossover == "bearish": score -= 2
        elif macd_hist is not None:
            if macd_hist > 0: score += 1
            else: score -= 1

        # Trend scoring (price vs moving averages)
        if sma_20 and price > sma_20: score += 1
        elif sma_20: score -= 1

        if sma_50 and price > sma_50: score += 1
        elif sma_50: score -= 1

        # Golden/Death cross
        golden = sma_50 is not None and sma_200 is not None and sma_50 > sma_200
        death = sma_50 is not None and sma_200 is not None and sma_50 < sma_200
        if golden: score += 1
        if death: score -= 1

        # Bollinger Band scoring
        if bb_position == "below_lower": score += 1  # Potentially oversold
        elif bb_position == "above_upper": score -= 1  # Potentially overbought

        # Volume confirmation
        if vol_ratio and vol_ratio > 1.5: score += 1  # High volume confirms move

        # Clamp score to -10 to +10
        score = max(-10, min(10, score))

        # Determine signal
        if score >= 5: signal = "strong_buy"
        elif score >= 2: signal = "buy"
        elif score <= -5: signal = "strong_sell"
        elif score <= -2: signal = "sell"
        else: signal = "neutral"

        rsi_signal = "neutral"
        if rsi_14 and rsi_14 < 30: rsi_signal = "oversold"
        elif rsi_14 and rsi_14 > 70: rsi_signal = "overbought"

        return TechnicalSignals(
            ticker=ticker, price=price,
            sma_20=sma_20, sma_50=sma_50, sma_200=sma_200,
            price_vs_sma20="above" if sma_20 and price > sma_20 else "below",
            price_vs_sma50="above" if sma_50 and price > sma_50 else "below",
            price_vs_sma200="above" if sma_200 and price > sma_200 else "below",
            golden_cross=golden, death_cross=death,
            rsi_14=rsi_14, rsi_signal=rsi_signal,
            macd=macd_val, macd_signal=macd_sig, macd_histogram=macd_hist,
            macd_crossover=macd_crossover,
            bb_upper=bb_upper, bb_lower=bb_lower, bb_position=bb_position,
            volume=curr_vol, avg_volume_20=avg_vol_20,
            volume_ratio=vol_ratio, high_volume=bool(vol_ratio and vol_ratio > 1.5),
            atr_14=atr_14, daily_volatility=daily_vol,
            score=score, signal=signal,
        )
    except Exception as e:
        logger.error("Failed to compute signals for %s: %s", ticker, e)
        return None

def compute_batch_signals(
    tickers: list[str], hist_map: dict | None = None
) -> dict[str, TechnicalSignals]:
    """Compute signals for multiple tickers. Skips failures.

    `hist_map` ({ticker: OHLCV frame}) reuses batch-downloaded history;
    missing tickers fall back to a per-ticker fetch."""
    results = {}
    for t in tickers:
        sig = compute_signals(t, hist=(hist_map or {}).get(t))
        if sig:
            results[t] = sig
    return results

def format_signal_card(sig: TechnicalSignals) -> str:
    """Format a signal into a human-readable card for LLM consumption."""
    lines = [
        f"{'='*50}",
        f"{sig.ticker}: ${sig.price:.2f} | Score: {sig.score:+d}/10 | Signal: {sig.signal.upper()}",
        f"{'='*50}",
    ]

    # RSI
    rsi_str = f"{sig.rsi_14:.0f}" if sig.rsi_14 else "N/A"
    lines.append(f"  RSI(14): {rsi_str} ({sig.rsi_signal})")

    # MACD
    if sig.macd is not None:
        lines.append(f"  MACD: {sig.macd:.3f} | Signal: {sig.macd_signal:.3f} | Hist: {sig.macd_histogram:.3f} ({sig.macd_crossover})")

    # Moving Averages
    if sig.sma_20:
        lines.append(f"  SMA20: ${sig.sma_20:.2f} ({sig.price_vs_sma20})")
    if sig.sma_50:
        lines.append(f"  SMA50: ${sig.sma_50:.2f} ({sig.price_vs_sma50})")
    if sig.sma_200:
        lines.append(f"  SMA200: ${sig.sma_200:.2f} ({sig.price_vs_sma200})")
    if sig.golden_cross:
        lines.append("  GOLDEN CROSS (SMA50 > SMA200)")
    if sig.death_cross:
        lines.append("  WARNING: DEATH CROSS (SMA50 < SMA200)")

    # Bollinger Bands
    if sig.bb_upper and sig.bb_lower:
        lines.append(f"  Bollinger: ${sig.bb_lower:.2f} -- ${sig.bb_upper:.2f} ({sig.bb_position})")

    # Volume
    vol_str = f"{sig.volume:,.0f}"
    avg_str = f"{sig.avg_volume_20:,.0f}" if sig.avg_volume_20 else "N/A"
    ratio_str = f"{sig.volume_ratio:.1f}x" if sig.volume_ratio else ""
    hv = " HIGH VOLUME" if sig.high_volume else ""
    lines.append(f"  Volume: {vol_str} (avg: {avg_str}) {ratio_str}{hv}")

    # ATR / Volatility
    if sig.atr_14:
        stop_loss = sig.price - 2 * sig.atr_14
        lines.append(f"  ATR(14): ${sig.atr_14:.2f} | Suggested Stop: ${stop_loss:.2f}")

    return "\n".join(lines)

def format_batch_signal_cards(signals: dict[str, TechnicalSignals]) -> str:
    """Format all signals into a single string for LLM prompt."""
    if not signals:
        return "No signal data available."

    # Sort by score (best first)
    sorted_sigs = sorted(signals.values(), key=lambda s: s.score, reverse=True)

    parts = ["QUANTITATIVE SIGNAL REPORT", "=" * 50, ""]

    # Summary table
    parts.append("SUMMARY (sorted by score):")
    for s in sorted_sigs:
        signal_label = s.signal.upper()
        parts.append(f"  {s.ticker:6s} Score:{s.score:+3d}  ${s.price:>8.2f}  RSI:{s.rsi_14 or 0:5.0f}  {signal_label}")

    parts.append("")

    # Detailed cards
    for s in sorted_sigs:
        parts.append(format_signal_card(s))
        parts.append("")

    return "\n".join(parts)
