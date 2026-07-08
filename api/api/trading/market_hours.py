"""Market-open guard using official exchange calendars (holidays included)."""

from __future__ import annotations

import functools
import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Exchange calendar codes: NYSE for US strategies, Taiwan Stock Exchange for TW
_CALENDAR_CODES = {"us": "XNYS", "tw": "XTAI"}


@functools.lru_cache(maxsize=2)
def _get_calendar(code: str):
    import exchange_calendars as xcals

    return xcals.get_calendar(code)


def is_market_open(market: str, now: pd.Timestamp | None = None) -> bool:
    """Return True if the exchange for `market` ("us" or "tw") is open right now.

    Fails open (returns True) if the calendar lookup errors, so a calendar
    problem degrades to pre-guard behavior instead of silently halting trading.
    """
    code = _CALENDAR_CODES.get(market, "XNYS")
    try:
        cal = _get_calendar(code)
        ts = now if now is not None else pd.Timestamp.now(tz="UTC")
        return bool(cal.is_open_on_minute(ts.floor("min")))
    except Exception as e:
        logger.warning("Market-open check failed for %s (%s): %s — failing open", market, code, e)
        return True
