"""Public Binance spot market-data ingestion and quality checks."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pandas as pd

from .config import MarketConfig
from .errors import MarketDataError
from .models import DataQuality, QualityGrade, SymbolTradingRules

LOGGER = logging.getLogger(__name__)

INTERVAL_SECONDS = {"1h": 3600, "4h": 14_400, "1d": 86_400}
BINANCE_BASE_URLS = ("https://data-api.binance.vision", "https://api.binance.com")
KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]


def normalize_symbol(symbol: str) -> str:
    """Validate and normalize a spot pair to Binance's compact form."""

    cleaned = symbol.strip().upper().replace("-", "/")
    if cleaned not in {"BTC/USDT", "ETH/USDT"}:
        raise MarketDataError("v0.1.2 supports only BTC/USDT and ETH/USDT")
    return cleaned.replace("/", "")


def parse_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    parsed = pd.Timestamp(value)
    parsed = parsed.tz_localize("UTC") if parsed.tzinfo is None else parsed.tz_convert("UTC")
    return parsed.to_pydatetime()


class BinancePublicClient:
    """Small, retry-limited client for public spot klines only."""

    def __init__(self, config: MarketConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self._client = client

    def _request_json(self, path: str, params: dict[str, Any]) -> Any:
        errors: list[str] = []
        for base_url in BINANCE_BASE_URLS:
            for attempt in range(1, self.config.max_retries + 1):
                try:
                    if self._client is None:
                        response = httpx.get(
                            f"{base_url}{path}",
                            params=params,
                            timeout=self.config.request_timeout_seconds,
                            follow_redirects=False,
                        )
                    else:
                        response = self._client.get(
                            f"{base_url}{path}",
                            params=params,
                            timeout=self.config.request_timeout_seconds,
                        )
                    response.raise_for_status()
                    payload = response.json()
                    LOGGER.info(
                        "public klines fetched",
                        extra={"event_data": {"base_url": base_url, "bars": len(payload)}},
                    )
                    return payload
                except (httpx.HTTPError, ValueError, MarketDataError) as exc:
                    errors.append(f"{base_url} attempt {attempt}: {type(exc).__name__}")
                    if attempt < self.config.max_retries:
                        time.sleep(min(0.25 * (2 ** (attempt - 1)), 1.0))
        raise MarketDataError(
            "public Binance request failed after bounded retries: " + "; ".join(errors)
        )

    def _request(self, params: dict[str, Any]) -> list[list[Any]]:
        payload = self._request_json("/api/v3/klines", params)
        if not isinstance(payload, list):
            raise MarketDataError("Binance returned a non-list kline payload")
        return payload

    def fetch_symbol_trading_rules(self, symbol: str) -> SymbolTradingRules:
        """Fetch public Binance spot precision and minimum-notional filters."""

        compact_symbol = normalize_symbol(symbol)
        payload = self._request_json("/api/v3/exchangeInfo", {"symbol": compact_symbol})
        try:
            symbols = payload["symbols"]
            item = next(value for value in symbols if value["symbol"] == compact_symbol)
            filters = {value["filterType"]: value for value in item["filters"]}
            price_filter = filters["PRICE_FILTER"]
            lot_filter = filters["LOT_SIZE"]
            market_lot = filters.get("MARKET_LOT_SIZE", {})
            market_step = float(market_lot.get("stepSize", 0))
            quantity_filter = market_lot if market_step > 0 else lot_filter
            notional_filter = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
            if notional_filter is None:
                raise KeyError("MIN_NOTIONAL/NOTIONAL")
            return SymbolTradingRules(
                symbol=symbol.upper().replace("-", "/"),
                price_tick_size=float(price_filter["tickSize"]),
                quantity_step_size=float(quantity_filter["stepSize"]),
                minimum_quantity=float(quantity_filter["minQty"]),
                maximum_quantity=(
                    float(quantity_filter["maxQty"])
                    if float(quantity_filter.get("maxQty", 0)) > 0
                    else None
                ),
                minimum_notional=float(notional_filter["minNotional"]),
                fetched_at=datetime.now(UTC),
                data_source="Binance public spot REST /api/v3/exchangeInfo",
            )
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            raise MarketDataError("Binance exchangeInfo is missing required spot filters") from exc

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        *,
        limit: int | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch recent or paginated historical klines and return UTC-indexed data."""

        if interval not in INTERVAL_SECONDS:
            raise MarketDataError(f"unsupported interval: {interval}")
        compact_symbol = normalize_symbol(symbol)
        start_dt, end_dt = parse_utc(start), parse_utc(end)
        target_limit = limit or self.config.history_limit
        if start_dt is None:
            payload = self._request(
                {"symbol": compact_symbol, "interval": interval, "limit": min(target_limit, 1000)}
            )
            return klines_to_frame(payload)

        cursor_ms = int(start_dt.timestamp() * 1000)
        end_ms = (
            int(end_dt.timestamp() * 1000) if end_dt else int(datetime.now(UTC).timestamp() * 1000)
        )
        rows: list[list[Any]] = []
        while cursor_ms < end_ms:
            batch = self._request(
                {
                    "symbol": compact_symbol,
                    "interval": interval,
                    "limit": 1000,
                    "startTime": cursor_ms,
                    "endTime": end_ms,
                }
            )
            if not batch:
                break
            rows.extend(batch)
            next_cursor = int(batch[-1][0]) + INTERVAL_SECONDS[interval] * 1000
            if next_cursor <= cursor_ms:
                raise MarketDataError("Binance pagination did not advance")
            cursor_ms = next_cursor
            if limit is not None and len(rows) >= limit:
                rows = rows[:limit]
                break
        return klines_to_frame(rows)


def klines_to_frame(payload: list[list[Any]]) -> pd.DataFrame:
    """Convert Binance's array response to a typed UTC DataFrame."""

    if not payload:
        raise MarketDataError("Binance returned no klines")
    if any(len(row) < len(KLINE_COLUMNS) for row in payload):
        raise MarketDataError("Binance returned malformed kline rows")
    frame = pd.DataFrame([row[: len(KLINE_COLUMNS)] for row in payload], columns=KLINE_COLUMNS)
    frame["timestamp"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    numeric = ["open", "high", "low", "close", "volume", "quote_volume"]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    frame["trade_count"] = (
        pd.to_numeric(frame["trade_count"], errors="coerce").fillna(0).astype(int)
    )
    result = frame.set_index("timestamp")[[*numeric, "trade_count"]]
    return result


def drop_incomplete_last_bar(
    frame: pd.DataFrame, interval: str, now: datetime | None = None
) -> pd.DataFrame:
    """Remove the currently forming candle so decisions use completed bars only."""

    if frame.empty:
        return frame
    now_utc = now or datetime.now(UTC)
    last_open = pd.Timestamp(frame.index[-1])
    if last_open.tzinfo is None:
        last_open = last_open.tz_localize("UTC")
    close_at = last_open + pd.Timedelta(seconds=INTERVAL_SECONDS[interval])
    if pd.Timestamp(now_utc) < close_at:
        return frame.iloc[:-1].copy()
    return frame


def validate_market_data(
    frame: pd.DataFrame,
    interval: str,
    *,
    minimum_bars: int = 210,
) -> DataQuality:
    """Assess ordering, duplicates, values, gaps, and usable history."""

    if interval not in INTERVAL_SECONDS:
        raise MarketDataError(f"unsupported interval: {interval}")
    issues: list[str] = []
    fatal = False
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        missing = sorted(required - set(frame.columns))
        issues.append(f"missing columns: {missing}")
        fatal = True
    duplicate_count = int(frame.index.duplicated(keep=False).sum())
    if duplicate_count:
        issues.append(f"duplicate timestamps: {duplicate_count}")
        fatal = True
    if not frame.index.is_monotonic_increasing:
        issues.append("timestamps are not strictly increasing")
        fatal = True
    if len(frame) < minimum_bars:
        issues.append(f"insufficient history: {len(frame)} < {minimum_bars}")
        fatal = True
    if required.issubset(frame.columns):
        numeric = frame[list(required)]
        if numeric.isna().any().any():
            issues.append("OHLCV contains non-numeric or missing values")
            fatal = True
        invalid_ohlc = (
            (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
            | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
            | (frame["volume"] < 0)
        )
        if bool(invalid_ohlc.any()):
            issues.append(f"invalid OHLCV rows: {int(invalid_ohlc.sum())}")
            fatal = True
    expected = pd.Timedelta(seconds=INTERVAL_SECONDS[interval])
    missing_intervals: list[str] = []
    if len(frame.index) > 1 and frame.index.is_monotonic_increasing:
        deltas = frame.index.to_series().diff().dropna()
        gaps = deltas[deltas > expected * 1.01]
        missing_intervals = [str(ts) for ts in gaps.index[:20]]
        if len(gaps):
            issues.append(f"time gaps detected: {len(gaps)}")
    grade = (
        QualityGrade.INVALID
        if fatal
        else QualityGrade.DEGRADED
        if missing_intervals
        else QualityGrade.VALID
    )
    return DataQuality(
        grade=grade,
        bars=len(frame),
        expected_interval=interval,
        duplicate_count=duplicate_count,
        gap_count=len(missing_intervals),
        missing_intervals=missing_intervals,
        issues=issues,
    )
