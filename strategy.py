"""
Calcolo indicatori tecnici e generazione segnali BUY/SELL/HOLD.
Usa pandas-ta su dati OHLCV 1h scaricati da Alpaca.
"""

from dataclasses import dataclass
from decimal import Decimal

import pandas as pd
import pandas_ta as ta
from loguru import logger


@dataclass
class SignalResult:
    symbol: str
    signal: str          # "BUY" | "SELL" | "HOLD"
    reason: str          # descrizione leggibile
    rsi: float
    ema20: float
    ema50: float
    ema200: float
    ema200_daily: float  # per verifica overnight
    macd_hist: float
    macd_bullish_cross: bool
    volume_ratio: float  # volume / media_20
    close: float
    vwap: float = 0.0   # VWAP giornaliero (anchor=D sui dati 1h)
    sell_reason: str | None = None  # motivo specifico del SELL


def _require_columns(df: pd.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Colonne mancanti nel DataFrame: {missing}")


def compute_indicators(df_1h: pd.DataFrame, df_daily: pd.DataFrame) -> pd.DataFrame:
    """
    Aggiunge RSI, EMA(20/50/200), MACD, Volume MA20 al DataFrame 1h.
    Modifica in-place e ritorna lo stesso DataFrame.
    """
    _require_columns(df_1h, ["open", "high", "low", "close", "volume"])

    df_1h = df_1h.copy()
    df_1h.sort_index(inplace=True)

    df_1h.ta.rsi(length=14, append=True)
    df_1h.ta.ema(length=20,  append=True)
    df_1h.ta.ema(length=50,  append=True)
    df_1h.ta.ema(length=200, append=True)
    df_1h.ta.macd(fast=12, slow=26, signal=9, append=True)
    df_1h["vol_ma20"] = df_1h["volume"].rolling(20).mean()

    # VWAP giornaliero: si resetta ogni sessione (anchor='D')
    # pandas-ta richiede che l'indice sia DatetimeTzAware per anchor giornaliero
    try:
        df_1h.ta.vwap(anchor="D", append=True)
    except Exception:
        df_1h["VWAP_D"] = (
            (df_1h["close"] * df_1h["volume"]).cumsum()
            / df_1h["volume"].cumsum()
        )

    # EMA200 daily: usa l'ultimo valore disponibile
    df_daily = df_daily.copy()
    df_daily.sort_index(inplace=True)
    df_daily.ta.ema(length=200, append=True)
    ema200_daily_val = float(df_daily["EMA_200"].dropna().iloc[-1]) if "EMA_200" in df_daily.columns and not df_daily["EMA_200"].dropna().empty else 0.0
    df_1h["ema200_daily"] = ema200_daily_val

    return df_1h


def _is_macd_bullish_cross(df: pd.DataFrame) -> bool:
    """True se nell'ultima candela il MACD ha attraversato al rialzo la signal line."""
    macd_col   = "MACD_12_26_9"
    signal_col = "MACDs_12_26_9"
    if macd_col not in df.columns or signal_col not in df.columns or len(df) < 2:
        return False
    prev = df.iloc[-2]
    last = df.iloc[-1]
    return (prev[macd_col] <= prev[signal_col]) and (last[macd_col] > last[signal_col])


def _is_macd_bearish_divergence(df: pd.DataFrame) -> bool:
    """Divergenza bearish semplice: prezzo fa nuovo massimo ma MACD histogram scende."""
    hist_col = "MACDh_12_26_9"
    if hist_col not in df.columns or len(df) < 3:
        return False
    last   = df.iloc[-1]
    prev   = df.iloc[-2]
    prev2  = df.iloc[-3]
    price_higher = last["close"] > prev["close"]
    hist_lower   = float(last[hist_col]) < float(prev[hist_col]) < float(prev2[hist_col])
    return price_higher and hist_lower


def _is_vix_proxy_spike(df_spy_1h: pd.DataFrame) -> bool:
    """SPY scende >1.5% nell'ultima candela 1h → nessun nuovo ingresso."""
    if len(df_spy_1h) < 2:
        return False
    last_close = float(df_spy_1h["close"].iloc[-1])
    prev_close = float(df_spy_1h["close"].iloc[-2])
    if prev_close <= 0:
        return False
    pct_change = (last_close - prev_close) / prev_close
    return pct_change < -0.015


def generate_signal(
    symbol: str,
    df_1h: pd.DataFrame,
    df_daily: pd.DataFrame,
    df_spy_1h: pd.DataFrame | None = None,
    existing_entry_price: float | None = None,
    tp1_hit: bool = False,
) -> SignalResult:
    """
    Genera il segnale per un asset dato il DataFrame con indicatori.
    existing_entry_price è necessario per valutare SL/TP su posizione aperta.
    """
    try:
        df = compute_indicators(df_1h, df_daily)
    except ValueError as e:
        logger.error(f"[{symbol}] Errore indicatori: {e}")
        return SignalResult(symbol=symbol, signal="HOLD", reason=str(e),
                            rsi=0, ema20=0, ema50=0, ema200=0, ema200_daily=0,
                            macd_hist=0, macd_bullish_cross=False, volume_ratio=1.0, close=0)

    last = df.iloc[-1]

    rsi          = float(last.get("RSI_14", 0))
    ema20        = float(last.get("EMA_20", 0))
    ema50        = float(last.get("EMA_50", 0))
    ema200       = float(last.get("EMA_200", 0))
    ema200_daily = float(last.get("ema200_daily", 0))
    macd_hist    = float(last.get("MACDh_12_26_9", 0))
    close        = float(last["close"])
    vol_ma20     = float(last.get("vol_ma20", 1)) or 1
    volume       = float(last["volume"])
    vol_ratio    = volume / vol_ma20
    # VWAP: pandas-ta può generare VWAP_D o VWAP a seconda della versione
    vwap_col = next((c for c in df.columns if c.startswith("VWAP")), None)
    vwap     = float(last[vwap_col]) if vwap_col and pd.notna(last[vwap_col]) else 0.0

    bullish_cross = _is_macd_bullish_cross(df)
    bearish_div   = _is_macd_bearish_divergence(df)

    _r = dict(rsi=rsi, ema20=ema20, ema50=ema50, ema200=ema200,
              ema200_daily=ema200_daily, macd_hist=macd_hist,
              macd_bullish_cross=bullish_cross, volume_ratio=vol_ratio,
              close=close, vwap=vwap)

    # --- Controlla SELL su posizione aperta ---
    if existing_entry_price and existing_entry_price > 0:
        entry = existing_entry_price
        sl_price  = entry * (1 - 0.03)
        tp1_price = entry * (1 + 0.04)
        tp2_price = entry * (1 + 0.08)

        if close <= sl_price:
            return SignalResult(symbol=symbol, signal="SELL", reason="Stop loss raggiunto",
                                sell_reason="stop_loss", **_r)

        if not tp1_hit and close >= tp1_price:
            return SignalResult(symbol=symbol, signal="SELL", reason="TP1 raggiunto (+4%)",
                                sell_reason="tp1", **_r)

        if tp1_hit and close >= tp2_price:
            return SignalResult(symbol=symbol, signal="SELL", reason="TP2 raggiunto (+8%)",
                                sell_reason="tp2", **_r)

        if rsi > 72:
            return SignalResult(symbol=symbol, signal="SELL", reason=f"RSI > 72 ({rsi:.1f})",
                                sell_reason="rsi_overbought", **_r)

        if bearish_div:
            return SignalResult(symbol=symbol, signal="SELL", reason="Divergenza bearish MACD",
                                sell_reason="macd_bearish", **_r)

    # --- Controlla BUY ---
    vix_spike = _is_vix_proxy_spike(df_spy_1h) if df_spy_1h is not None else False
    if vix_spike:
        return SignalResult(symbol=symbol, signal="HOLD",
                            reason="VIX proxy: SPY -1.5% in 1h, no nuovi ingressi", **_r)

    buy_rsi    = 35 <= rsi <= 50
    buy_ema    = close > ema50
    buy_macd   = macd_hist > 0 or bullish_cross
    buy_volume = vol_ratio >= 1.3
    buy_vwap   = close > vwap if vwap > 0 else True  # ignora se VWAP non disponibile

    if buy_rsi and buy_ema and buy_macd and buy_volume and buy_vwap:
        return SignalResult(symbol=symbol, signal="BUY",
                            reason="Tutti i criteri BUY soddisfatti (incl. VWAP)", **_r)

    # Costruisce ragione HOLD leggibile
    missing = []
    if not buy_rsi:    missing.append(f"RSI={rsi:.1f} (serve 35-50)")
    if not buy_ema:    missing.append("close < EMA50")
    if not buy_macd:   missing.append("MACD non bullish")
    if not buy_volume: missing.append(f"volume {vol_ratio:.1f}x (serve ≥1.3x)")
    if not buy_vwap:   missing.append(f"close < VWAP ${vwap:.2f}")

    return SignalResult(symbol=symbol, signal="HOLD",
                        reason="Condizioni BUY non soddisfatte: " + "; ".join(missing), **_r)
