"""
Sizing, regole di pausa, orari, overnight.
Tutte le decisioni di rischio passano da qui.
"""

import json
import os
from datetime import date
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from loguru import logger

import market_hours as mh

RISK_STATE_FILE = Path("risk_state.json")

# Carica configurazione da env con valori di default sicuri
CAPITALE_TOTALE   = Decimal(os.getenv("CAPITALE_TOTALE", "100"))
RISCHIO_PER_TRADE = Decimal(os.getenv("RISCHIO_PER_TRADE", "0.015"))

# Allocazione percentuale per asset
ASSET_ALLOCATIONS: dict[str, Decimal] = {
    "SPY": Decimal("0.50"),
    "QQQ": Decimal("0.30"),
    "IWM": Decimal("0.20"),
}

SL_PCT  = Decimal("0.03")   # 3% stop loss
TP1_PCT = Decimal("0.04")   # 4% take profit 1
TP2_PCT = Decimal("0.08")   # 8% take profit 2

MAX_CONSECUTIVE_SL  = 2
PAUSE_AFTER_SL_DAYS = 1
NO_ENTRY_COOLDOWN_S = 7200  # 2 ore in secondi


def _load_state() -> dict:
    if not RISK_STATE_FILE.exists():
        return {"consecutive_sl": 0, "pause_until_date": None}
    try:
        with RISK_STATE_FILE.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"consecutive_sl": 0, "pause_until_date": None}


def _save_state(state: dict) -> None:
    tmp = RISK_STATE_FILE.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(RISK_STATE_FILE)


def record_stop_loss() -> int:
    """Registra uno SL e ritorna il conteggio corrente."""
    state = _load_state()
    state["consecutive_sl"] = state.get("consecutive_sl", 0) + 1
    if state["consecutive_sl"] >= MAX_CONSECUTIVE_SL:
        next_td = mh.next_trading_day()
        state["pause_until_date"] = next_td.isoformat()
        logger.warning(f"Pausa attivata fino a {next_td}")
    _save_state(state)
    return state["consecutive_sl"]


def record_profitable_trade() -> None:
    """Un trade in profitto azzera il contatore SL consecutivi."""
    state = _load_state()
    state["consecutive_sl"] = 0
    _save_state(state)


def is_bot_paused() -> bool:
    state = _load_state()
    pause_until = state.get("pause_until_date")
    if not pause_until:
        return False
    try:
        pause_date = date.fromisoformat(pause_until)
        today = mh.today_et()
        if today >= pause_date:
            # La pausa è scaduta: resetta
            state["pause_until_date"] = None
            state["consecutive_sl"] = 0
            _save_state(state)
            return False
        return True
    except ValueError:
        return False


def consecutive_sl_count() -> int:
    return _load_state().get("consecutive_sl", 0)


def can_open_position(symbol: str, seconds_since_last_close: float) -> tuple[bool, str]:
    """
    Verifica tutte le regole prima di aprire una nuova posizione.
    Ritorna (True, "") oppure (False, "motivo").
    """
    if is_bot_paused():
        return False, "bot in pausa (2 SL consecutivi)"

    if not mh.is_trading_day():
        return False, "mercato chiuso (weekend/festività)"

    if not mh.is_market_open_local():
        return False, "fuori orario di mercato"

    if mh.is_last_trading_hour():
        return False, "ultima ora di trading (15:00–16:00 ET)"

    if mh.is_friday_afternoon():
        return False, "venerdì pomeriggio (no nuovi ingressi)"

    if seconds_since_last_close > 0 and seconds_since_last_close < NO_ENTRY_COOLDOWN_S:
        wait_min = int((NO_ENTRY_COOLDOWN_S - seconds_since_last_close) / 60)
        return False, f"cooldown 2h: ancora {wait_min} minuti"

    return True, ""


def compute_position_size(symbol: str, current_capital: Decimal) -> Decimal:
    """Ritorna il valore in USD da allocare per il simbolo."""
    alloc = ASSET_ALLOCATIONS.get(symbol, Decimal("0"))
    return (current_capital * alloc).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def compute_shares(size_usd: Decimal, price: Decimal) -> Decimal:
    """Numero di azioni (frazioni) da acquistare."""
    if price <= 0:
        return Decimal("0")
    return (size_usd / price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)


def compute_sl_price(entry: Decimal) -> Decimal:
    return (entry * (1 - SL_PCT)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def compute_tp1_price(entry: Decimal) -> Decimal:
    return (entry * (1 + TP1_PCT)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def compute_tp2_price(entry: Decimal) -> Decimal:
    return (entry * (1 + TP2_PCT)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def is_overnight_allowed(ema200_daily: float, current_close: float) -> bool:
    """Posizioni overnight solo se close > EMA200 daily."""
    return current_close > ema200_daily
