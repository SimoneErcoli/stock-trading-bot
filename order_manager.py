"""
Gestione ciclo di vita degli ordini: bracket, polling, cancellazione,
retry su ordine non eseguito, aggiornamento SL dopo TP1.
"""

import time
from decimal import Decimal

from loguru import logger

import alpaca_client as ac
import position_manager as pm
import risk_manager as rm
import telegram_notify as tg

ORDER_FILL_TIMEOUT_S = 300   # 5 minuti prima di ritirare l'ordine
POLL_INTERVAL_S      = 15    # controlla lo stato ogni 15 secondi


def _poll_order_until_filled(order_id: str, timeout_s: int = ORDER_FILL_TIMEOUT_S) -> object | None:
    """
    Polling sull'ordine finché non è filled o scade il timeout.
    Ritorna l'oggetto ordine filled oppure None se non eseguito.
    """
    elapsed = 0
    while elapsed < timeout_s:
        order = ac.get_order(order_id)
        if order is None:
            return None
        status = str(order.status).lower()
        if status == "filled":
            return order
        if status in ("canceled", "expired", "rejected"):
            logger.warning(f"Ordine {order_id} terminato con status: {status}")
            return None
        time.sleep(POLL_INTERVAL_S)
        elapsed += POLL_INTERVAL_S
    return None


def open_new_position(
    symbol: str,
    signal_close: float,
    current_capital: Decimal,
) -> bool:
    """
    Apre una nuova posizione bracket per il simbolo.
    Ritorna True se la posizione è stata aperta con successo.
    """
    buying_power = ac.get_buying_power()
    size_usd = rm.compute_position_size(symbol, current_capital)

    if buying_power < size_usd:
        logger.warning(f"[{symbol}] Buying power insufficiente: {buying_power} < {size_usd}")
        return False

    price = Decimal(str(signal_close))
    limit_price = float(price + Decimal("0.01"))
    shares      = float(rm.compute_shares(size_usd, price))

    if shares <= 0:
        logger.warning(f"[{symbol}] Quantità calcolata = 0, skip")
        return False

    sl_price  = float(rm.compute_sl_price(price))
    tp1_price = float(rm.compute_tp1_price(price))
    tp2_price = float(rm.compute_tp2_price(price))

    # Notifica ordine inviato
    tg.send_order_sent(
        symbol=symbol,
        limit_price=limit_price,
        qty=shares,
        size_usd=float(size_usd),
        sl_price=sl_price,
        tp1_price=tp1_price,
    )

    order = ac.place_bracket_order(
        symbol=symbol,
        qty=shares,
        limit_price=limit_price,
        sl_price=sl_price,
        tp1_price=tp1_price,
    )
    if order is None:
        tg.send_error(f"[{symbol}] Errore invio bracket order")
        return False

    logger.info(f"[{symbol}] Bracket order {order.id} inviato, attendo fill…")
    filled_order = _poll_order_until_filled(order.id)

    if filled_order is None:
        # Timeout: cancella e riprova con prezzo aggiornato
        logger.warning(f"[{symbol}] Ordine non eseguito in {ORDER_FILL_TIMEOUT_S}s, ritiro e riprovo")
        ac.cancel_order(order.id)
        new_price = ac.get_latest_price(symbol)
        if new_price <= 0:
            return False
        new_limit  = float(new_price + Decimal("0.01"))
        new_shares = float(rm.compute_shares(size_usd, new_price))
        retry_order = ac.place_bracket_order(
            symbol=symbol,
            qty=new_shares,
            limit_price=new_limit,
            sl_price=float(rm.compute_sl_price(new_price)),
            tp1_price=float(rm.compute_tp1_price(new_price)),
        )
        if retry_order is None:
            return False
        filled_order = _poll_order_until_filled(retry_order.id)
        if filled_order is None:
            ac.cancel_order(retry_order.id)
            return False

    # Ordine eseguito
    exec_price  = float(filled_order.filled_avg_price or limit_price)
    exec_shares = float(filled_order.filled_qty or shares)
    exec_price_d = Decimal(str(exec_price))

    # Cerca ID degli ordini leg SL e TP1 generati dal bracket
    sl_id  = _find_leg_order_id(filled_order, "stop")
    tp1_id = _find_leg_order_id(filled_order, "limit")

    pm.open_position(
        symbol=symbol,
        entry_price=exec_price,
        shares=exec_shares,
        size_usd=float(size_usd),
        order_id_entry=str(filled_order.id),
        order_id_sl=sl_id or "",
        order_id_tp1=tp1_id or "",
        order_id_tp2="",
        sl=float(rm.compute_sl_price(exec_price_d)),
        tp1=float(rm.compute_tp1_price(exec_price_d)),
        tp2=float(rm.compute_tp2_price(exec_price_d)),
    )

    pos = pm.get_position(symbol)
    tg.send_position_opened(symbol=symbol, pos=pos, signal_rsi=0,
                             above_ema50=True, macd_bull=True, vol_ratio=0)
    logger.info(f"[{symbol}] Posizione aperta a {exec_price}")
    return True


def _find_leg_order_id(parent_order, leg_type: str) -> str | None:
    """Cerca tra i legs del bracket l'ID dell'ordine SL o TP."""
    try:
        legs = getattr(parent_order, "legs", None) or []
        for leg in legs:
            if leg_type == "stop" and str(getattr(leg, "type", "")).lower() == "stop":
                return str(leg.id)
            if leg_type == "limit" and str(getattr(leg, "type", "")).lower() == "limit":
                return str(leg.id)
    except Exception:
        pass
    return None


def handle_tp1(symbol: str) -> None:
    """
    TP1 raggiunto: vende 50% della posizione, sposta SL al breakeven,
    piazza ordine TP2.
    """
    pos = pm.get_position(symbol)
    if not pos.get("active"):
        return

    entry_price = float(pos["entry_price"])
    shares      = float(pos["shares"])
    half_shares = round(shares / 2, 6)
    tp1_price   = float(pos["tp1"])
    tp2_price   = float(pos["tp2"])
    old_sl_id   = pos.get("order_id_sl", "")

    # Cancella SL originale
    if old_sl_id:
        ac.cancel_order(old_sl_id)

    # Vendi metà
    sell_order = ac.place_limit_sell(symbol, half_shares, tp1_price)

    # Piazza nuovo SL al breakeven
    new_sl_order = ac.place_stop_order(symbol, half_shares, entry_price)
    new_sl_id    = str(new_sl_order.id) if new_sl_order else ""

    # Piazza ordine TP2
    tp2_order = ac.place_limit_sell(symbol, half_shares, tp2_price)
    tp2_id    = str(tp2_order.id) if tp2_order else ""

    pm.mark_tp1_hit(symbol, new_sl=entry_price)
    pm.update_order_ids(symbol, order_id_sl=new_sl_id, order_id_tp2=tp2_id)

    profit = (tp1_price - entry_price) * half_shares
    tg.send_tp1_hit(symbol=symbol, tp1_price=tp1_price, qty_sold=half_shares,
                    profit=profit, breakeven=entry_price, tp2_price=tp2_price,
                    remaining_shares=half_shares, remaining_usd=half_shares * tp1_price)
    rm.record_profitable_trade()
    logger.info(f"[{symbol}] TP1 hit, SL spostato al breakeven {entry_price}")


def handle_stop_loss(symbol: str, fill_price: float) -> None:
    """SL raggiunto: chiude tutto e aggiorna stato."""
    pos = pm.get_position(symbol)
    if not pos.get("active"):
        return

    entry_price = float(pos["entry_price"])
    shares      = float(pos["shares"])
    loss        = (fill_price - entry_price) * shares

    pm.close_position(symbol)
    sl_count = rm.record_stop_loss()

    tg.send_stop_loss(symbol=symbol, fill_price=fill_price, loss=loss, sl_count=sl_count)

    if sl_count >= rm.MAX_CONSECUTIVE_SL:
        tg.send_pause_alert(loss_total=loss)

    logger.warning(f"[{symbol}] SL eseguito a {fill_price}, perdita {loss:.2f}")


def close_position_market(symbol: str, reason: str = "chiusura manuale") -> None:
    """Chiude la posizione a mercato (fine giornata in perdita, ecc.)."""
    pos = pm.get_position(symbol)
    if not pos.get("active"):
        return

    shares = float(pos["shares"])
    order  = ac.place_market_sell(symbol, shares)
    if order:
        pm.close_position(symbol)
        logger.info(f"[{symbol}] Chiuso a mercato: {reason}")


def check_open_orders_status(symbol: str) -> None:
    """
    Controlla se gli ordini SL/TP1/TP2 sono stati eseguiti da Alpaca
    e aggiorna lo stato locale di conseguenza.
    """
    pos = pm.get_position(symbol)
    if not pos.get("active"):
        return

    entry_price = float(pos.get("entry_price", 0))
    tp1_hit     = pos.get("tp1_hit", False)

    # Controlla SL
    sl_id = pos.get("order_id_sl")
    if sl_id:
        sl_order = ac.get_order(sl_id)
        if sl_order and str(sl_order.status).lower() == "filled":
            fill = float(sl_order.filled_avg_price or entry_price * 0.97)
            handle_stop_loss(symbol, fill)
            return

    # Controlla TP1 (se non ancora colpito)
    if not tp1_hit:
        tp1_id = pos.get("order_id_tp1")
        if tp1_id:
            tp1_order = ac.get_order(tp1_id)
            if tp1_order and str(tp1_order.status).lower() == "filled":
                handle_tp1(symbol)
                return

    # Controlla TP2
    if tp1_hit:
        tp2_id = pos.get("order_id_tp2")
        if tp2_id:
            tp2_order = ac.get_order(tp2_id)
            if tp2_order and str(tp2_order.status).lower() == "filled":
                fill    = float(tp2_order.filled_avg_price or pos.get("tp2", 0))
                profit  = (fill - entry_price) * float(pos["shares"])
                pm.close_position(symbol)
                rm.record_profitable_trade()
                tg.send_generic(
                    f"🏁 TP2 RAGGIUNTO — {symbol}\n"
                    f"✅ Chiuso a ${fill:.2f}\n"
                    f"💰 Profitto totale stimato: +${profit:.2f}"
                )
                logger.info(f"[{symbol}] TP2 hit a {fill}")
