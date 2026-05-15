"""
Lettura e scrittura dello stato delle posizioni su positions.json.
Unica fonte di verità per lo stato locale del bot.
"""

import json
import os
from datetime import datetime, UTC
from decimal import Decimal
from pathlib import Path
from typing import Any

from loguru import logger

POSITIONS_FILE = Path("positions.json")

_EMPTY_POSITION: dict[str, Any] = {
    "active": False,
    "entry_price": None,
    "entry_time": None,
    "shares": 0,
    "size_usd": 0.0,
    "order_id_entry": None,
    "order_id_sl": None,
    "order_id_tp1": None,
    "order_id_tp2": None,
    "sl": None,
    "tp1": None,
    "tp2": None,
    "tp1_hit": False,
    "tp2_hit": False,
    "overnight": False,
    "last_closed_time": None,
}


def _load() -> dict[str, Any]:
    if not POSITIONS_FILE.exists():
        return {}
    try:
        with POSITIONS_FILE.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Errore lettura positions.json: {e}")
        return {}


def _save(data: dict[str, Any]) -> None:
    tmp = POSITIONS_FILE.with_suffix(".tmp")
    try:
        with tmp.open("w") as f:
            json.dump(data, f, indent=2, default=str)
        tmp.replace(POSITIONS_FILE)
    except OSError as e:
        logger.error(f"Errore scrittura positions.json: {e}")
        raise


def get_position(symbol: str) -> dict[str, Any]:
    data = _load()
    return data.get(symbol, dict(_EMPTY_POSITION))


def get_all_positions() -> dict[str, Any]:
    return _load()


def set_position(symbol: str, pos: dict[str, Any]) -> None:
    data = _load()
    data[symbol] = pos
    _save(data)
    logger.debug(f"Posizione aggiornata: {symbol} active={pos.get('active')}")


def open_position(
    symbol: str,
    entry_price: float,
    shares: float,
    size_usd: float,
    order_id_entry: str,
    order_id_sl: str,
    order_id_tp1: str,
    order_id_tp2: str,
    sl: float,
    tp1: float,
    tp2: float,
) -> None:
    pos = dict(_EMPTY_POSITION)
    pos.update(
        active=True,
        entry_price=entry_price,
        entry_time=datetime.now(UTC).isoformat(),
        shares=shares,
        size_usd=size_usd,
        order_id_entry=order_id_entry,
        order_id_sl=order_id_sl,
        order_id_tp1=order_id_tp1,
        order_id_tp2=order_id_tp2,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        tp1_hit=False,
        tp2_hit=False,
        overnight=False,
    )
    set_position(symbol, pos)


def close_position(symbol: str) -> None:
    pos = get_position(symbol)
    pos["active"] = False
    pos["last_closed_time"] = datetime.now(UTC).isoformat()
    set_position(symbol, pos)


def mark_tp1_hit(symbol: str, new_sl: float) -> None:
    pos = get_position(symbol)
    pos["tp1_hit"] = True
    pos["sl"] = new_sl
    pos["shares"] = float(Decimal(str(pos["shares"])) / 2)
    pos["size_usd"] = float(Decimal(str(pos["size_usd"])) / 2)
    set_position(symbol, pos)


def mark_overnight(symbol: str, overnight: bool) -> None:
    pos = get_position(symbol)
    pos["overnight"] = overnight
    set_position(symbol, pos)


def is_active(symbol: str) -> bool:
    return get_position(symbol).get("active", False)


def seconds_since_close(symbol: str) -> float:
    """Secondi passati dall'ultima chiusura. -1 se mai chiusa."""
    pos = get_position(symbol)
    closed_at = pos.get("last_closed_time")
    if not closed_at:
        return -1.0
    try:
        t = datetime.fromisoformat(closed_at)
        return (datetime.now(UTC) - t).total_seconds()
    except ValueError:
        return -1.0


def update_order_ids(
    symbol: str,
    order_id_sl: str | None = None,
    order_id_tp1: str | None = None,
    order_id_tp2: str | None = None,
) -> None:
    pos = get_position(symbol)
    if order_id_sl is not None:
        pos["order_id_sl"] = order_id_sl
    if order_id_tp1 is not None:
        pos["order_id_tp1"] = order_id_tp1
    if order_id_tp2 is not None:
        pos["order_id_tp2"] = order_id_tp2
    set_position(symbol, pos)
