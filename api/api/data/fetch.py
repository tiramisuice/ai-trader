"""Retried low-level yfinance fetchers shared by the data and quant modules.

yfinance is rate-limited and flaky; a transient failure used to silently become
"no signal" (or a zero price). Retry with exponential backoff, then reraise so
each caller's existing error handling still decides how to degrade.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

YF_RETRY = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,
)


@YF_RETRY
def fetch_info(ticker: str) -> dict:
    return yf.Ticker(ticker).info or {}


@YF_RETRY
def fetch_history(ticker: str, period: str) -> pd.DataFrame:
    return yf.Ticker(ticker).history(period=period)


@YF_RETRY
def fetch_insider_transactions(ticker: str) -> pd.DataFrame | None:
    return yf.Ticker(ticker).insider_transactions


@YF_RETRY
def fetch_insider_purchases(ticker: str) -> pd.DataFrame | None:
    return yf.Ticker(ticker).insider_purchases
