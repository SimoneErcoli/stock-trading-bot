"""
Wrapper attorno ad alpaca-py.
Gestisce dati storici, clock, account e invio ordini.
"""

import os
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce, OrderClass
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    StopOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
    GetOrdersRequest,
)
from loguru import logger

ET = ZoneInfo("America/New_York")


def _build_clients() -> tuple[TradingClient, StockHistoricalDataClient]:
    api_key    = os.environ["ALPACA_API_KEY"]
    api_secret = os.environ["ALPACA_API_SECRET"]
    base_url   = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    paper      = "paper" in base_url

    trading = TradingClient(api_key, api_secret, paper=paper)
    data    = StockHistoricalDataClient(api_key, api_secret)
    return trading, data


# Singleton leggero: costruiti la prima volta che serve
_trading_client: TradingClient | None = None
_data_client: StockHistoricalDataClient | None = None


def _trading() -> TradingClient:
    global _trading_client
    if _trading_client is None:
        _trading_client, _ = _build_clients()
    return _trading_client


def _data() -> StockHistoricalDataClient:
    global _data_client
    if _data_client is None:
        _, _data_client = _build_clients()
    return _data_client


# ── Clock e account ────────────────────────────────────────────────────────────

def get_clock():
    """Ritorna l'oggetto Clock di Alpaca."""
    return _trading().get_clock()


def is_market_open() -> bool:
    try:
        return bool(get_clock().is_open)
    except Exception as e:
        logger.error(f"Errore get_clock: {e}")
        return False


def get_account():
    return _trading().get_account()


def get_buying_power() -> Decimal:
    try:
        acct = get_account()
        return Decimal(str(acct.buying_power))
    except Exception as e:
        logger.error(f"Errore get_account: {e}")
        return Decimal("0")


def get_portfolio_value() -> Decimal:
    try:
        acct = get_account()
        return Decimal(str(acct.portfolio_value))
    except Exception as e:
        logger.error(f"Errore get_account: {e}")
        return Decimal("0")


# ── Dati storici ───────────────────────────────────────────────────────────────

def get_bars_1h(symbol: str, bars: int = 200) -> pd.DataFrame:
    """Scarica le ultime `bars` candele 1h. Ritorna DataFrame OHLCV."""
    end   = datetime.now(ET)
    start = end - timedelta(hours=bars * 2)  # margine per weekend/festività
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Hour,
        start=start,
        end=end,
        limit=bars,
    )
    try:
        bars_data = _data().get_stock_bars(req)
        df = bars_data.df
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        df.index = pd.to_datetime(df.index)
        logger.debug(f"[{symbol}] Scaricate {len(df)} candele 1h")
        return df
    except Exception as e:
        logger.error(f"[{symbol}] Errore get_bars_1h: {e}")
        return pd.DataFrame()


def get_bars_daily(symbol: str, bars: int = 250) -> pd.DataFrame:
    """Scarica le ultime `bars` candele daily (per EMA200 daily)."""
    end   = datetime.now(ET)
    start = end - timedelta(days=bars + 60)
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        limit=bars,
    )
    try:
        bars_data = _data().get_stock_bars(req)
        df = bars_data.df
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        logger.error(f"[{symbol}] Errore get_bars_daily: {e}")
        return pd.DataFrame()


def get_latest_price(symbol: str) -> Decimal:
    """Ultimo prezzo disponibile (close dell'ultima candela 1h)."""
    df = get_bars_1h(symbol, bars=2)
    if df.empty:
        return Decimal("0")
    return Decimal(str(df["close"].iloc[-1]))


# ── Ordini ─────────────────────────────────────────────────────────────────────

def place_bracket_order(
    symbol: str,
    qty: float,
    limit_price: float,
    sl_price: float,
    tp1_price: float,
) -> object | None:
    """
    Ordine bracket: limit buy + SL stop + TP1 limit.
    Ritorna l'oggetto ordine Alpaca o None in caso di errore.
    """
    try:
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2),
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(tp1_price, 2)),
            stop_loss=StopLossRequest(stop_price=round(sl_price, 2)),
        )
        order = _trading().submit_order(req)
        logger.info(f"[{symbol}] Bracket order inviato: {order.id}")
        return order
    except Exception as e:
        logger.error(f"[{symbol}] Errore bracket order: {e}")
        return None


def place_limit_sell(
    symbol: str,
    qty: float,
    limit_price: float,
) -> object | None:
    """Ordine limit sell (per TP2 o chiusura manuale)."""
    try:
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2),
        )
        order = _trading().submit_order(req)
        logger.info(f"[{symbol}] Limit sell inviato: {order.id}")
        return order
    except Exception as e:
        logger.error(f"[{symbol}] Errore limit sell: {e}")
        return None


def place_market_sell(symbol: str, qty: float) -> object | None:
    """Market sell per chiusure urgenti (SL non eseguito, fine giornata)."""
    try:
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = _trading().submit_order(req)
        logger.info(f"[{symbol}] Market sell inviato: {order.id}")
        return order
    except Exception as e:
        logger.error(f"[{symbol}] Errore market sell: {e}")
        return None


def place_stop_order(symbol: str, qty: float, stop_price: float) -> object | None:
    """Stop order nativo (nuovo SL dopo TP1)."""
    try:
        req = StopOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            stop_price=round(stop_price, 2),
            time_in_force=TimeInForce.GTC,
        )
        order = _trading().submit_order(req)
        logger.info(f"[{symbol}] Stop order inviato a {stop_price}: {order.id}")
        return order
    except Exception as e:
        logger.error(f"[{symbol}] Errore stop order: {e}")
        return None


def cancel_order(order_id: str) -> bool:
    try:
        _trading().cancel_order_by_id(order_id)
        logger.info(f"Ordine {order_id} cancellato")
        return True
    except Exception as e:
        logger.warning(f"Errore cancellazione ordine {order_id}: {e}")
        return False


def get_order(order_id: str):
    try:
        return _trading().get_order_by_id(order_id)
    except Exception as e:
        logger.warning(f"Errore get_order {order_id}: {e}")
        return None


def get_open_positions() -> dict[str, object]:
    """Ritorna {symbol: posizione} per le posizioni aperte su Alpaca."""
    try:
        positions = _trading().get_all_positions()
        return {p.symbol: p for p in positions}
    except Exception as e:
        logger.error(f"Errore get_all_positions: {e}")
        return {}
