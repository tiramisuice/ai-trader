"""Batch OHLCV download shared by signals and factors.

One `yf.download` call per cycle replaces ~2 history fetches per ticker
(signals + factors both pulled 1y independently), cutting network round-trips
and rate-limit pressure dramatically.
"""

from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

from api.data.fetch import YF_RETRY

logger = logging.getLogger(__name__)


@YF_RETRY
def _download(tickers: list[str], period: str) -> pd.DataFrame:
    return yf.download(
        tickers, period=period, group_by="ticker",
        auto_adjust=True, progress=False, threads=True,
    )


def fetch_batch_history(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Download history for many tickers at once. Returns {ticker: OHLCV frame}.

    Tickers that fail to download are simply absent — callers fall back to a
    per-ticker fetch (or skip) as they see fit.
    """
    if not tickers:
        return {}
    try:
        data = _download(list(tickers), period)
    except Exception as e:
        logger.warning("Batch history download failed for %d tickers: %s", len(tickers), e)
        return {}

    result: dict[str, pd.DataFrame] = {}
    if len(tickers) == 1:
        df = data.dropna(how="all")
        if not df.empty:
            result[tickers[0]] = df
        return result

    for t in tickers:
        try:
            df = data[t].dropna(how="all")
            if not df.empty:
                result[t] = df
        except KeyError:
            logger.warning("Batch download missing %s", t)
    return result
