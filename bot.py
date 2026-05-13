"""
Entry point del bot. Loop orario con schedule.
Opera solo negli orari di mercato USA.
"""

import os
import sys
import time
from datetime import date
from decimal import Decimal

import schedule
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# Configura loguru prima di importare i moduli interni
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")
logger.add(
    "bot.log",
    rotation="1 day",
    retention="7 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}",
)

import alpaca_client as ac
import market_hours as mh
import order_manager as om
import position_manager as pm
import risk_manager as rm
import strategy as st
import telegram_notify as tg

ASSETS    = ["SPY", "QQQ", "IWM"]
VERSION   = "1.0"

# Capitale di riferimento (aggiornato ogni ciclo dal portfolio Alpaca)
_capital_cache: Decimal = rm.CAPITALE_TOTALE


def _get_current_capital() -> Decimal:
    val = ac.get_portfolio_value()
    if val > 0:
        return val
    return rm.CAPITALE_TOTALE


def _trend_arrow(rsi: float, ema20: float, ema50: float, close: float) -> str:
    if close > ema50 and rsi < 60:
        return "▲"
    if close < ema50:
        return "▼"
    return "→"


# ── Pre-market briefing ────────────────────────────────────────────────────────

def run_pre_market_briefing() -> None:
    logger.info("Invio briefing pre-mercato")
    assets_info   = []
    open_pos_syms = []
    potential     = []

    for symbol in ASSETS:
        try:
            df_1h    = ac.get_bars_1h(symbol, bars=50)
            df_daily = ac.get_bars_daily(symbol, bars=250)
            if df_1h.empty:
                continue
            sig = st.generate_signal(symbol, df_1h, df_daily)
            assets_info.append({
                "symbol": symbol,
                "price":  sig.close,
                "rsi":    sig.rsi,
                "trend":  _trend_arrow(sig.rsi, sig.ema20, sig.ema50, sig.close),
            })
            if pm.is_active(symbol):
                pos     = pm.get_position(symbol)
                entry   = float(pos["entry_price"])
                pct_chg = (sig.close - entry) / entry * 100 if entry else 0
                open_pos_syms.append(f"{symbol} ({pct_chg:+.1f}%)")
            if sig.signal == "BUY":
                potential.append(f"{symbol} (RSI in zona buy)")
        except Exception as e:
            logger.error(f"[{symbol}] Briefing error: {e}")
            tg.send_error(f"[{symbol}] Errore briefing: {e}")

    portfolio_val = float(_get_current_capital())
    tg.send_pre_market_briefing(
        assets=assets_info,
        portfolio_value=portfolio_val,
        open_positions=open_pos_syms,
        potential_setups=potential,
        today=mh.today_et(),
    )


# ── Market close report ────────────────────────────────────────────────────────

def run_market_close_report() -> None:
    logger.info("Invio report chiusura mercato")
    portfolio_val = float(_get_current_capital())
    initial       = float(rm.CAPITALE_TOTALE)
    pnl_today     = portfolio_val - initial
    pct           = pnl_today / initial * 100 if initial else 0

    overnight_info = []
    for symbol in ASSETS:
        if not pm.is_active(symbol):
            continue
        pos   = pm.get_position(symbol)
        entry = float(pos["entry_price"])
        try:
            df_1h    = ac.get_bars_1h(symbol, bars=50)
            df_daily = ac.get_bars_daily(symbol, bars=250)
            sig      = st.generate_signal(symbol, df_1h, df_daily)
            current  = sig.close
            pct_chg  = (current - entry) / entry * 100 if entry else 0
            trend_ok = rm.is_overnight_allowed(sig.ema200_daily, current)

            overnight_info.append({
                "symbol":          symbol,
                "entry":           entry,
                "unrealized_pct":  pct_chg,
                "trend_ok":        trend_ok,
            })

            pm.mark_overnight(symbol, overnight=True)

            if not trend_ok or sig.rsi > 72:
                logger.info(f"[{symbol}] Chiusura overnight: trend_ok={trend_ok}, RSI={sig.rsi:.1f}")
                om.close_position_market(symbol, reason="chiusura fine giornata")

        except Exception as e:
            logger.error(f"[{symbol}] Close report error: {e}")

    # Recupera i trade chiusi oggi da risk_state (semplificato)
    next_day = mh.next_trading_day()
    next_str = next_day.strftime("%A %d/%m") + " 09:30 ET"
    if mh.today_et().weekday() == 4:  # venerdì
        next_str = "lunedì " + next_day.strftime("%d/%m") + " 09:30 ET"

    tg.send_market_close_report(
        portfolio_value=portfolio_val,
        portfolio_pct=pct,
        pnl_today=pnl_today,
        closed_trades=[],   # TODO: tracciare trade chiusi intraday
        overnight_positions=overnight_info,
        next_open_str=next_str,
        today=mh.today_et(),
    )


# ── Loop principale (ogni ora) ─────────────────────────────────────────────────

def run_hourly_cycle() -> None:
    global _capital_cache

    if not mh.is_trading_day():
        logger.debug("Giorno non lavorativo, skip")
        return

    # Verifica mercato aperto tramite Alpaca clock (più affidabile per festività)
    try:
        market_open = ac.is_market_open()
    except Exception as e:
        logger.warning(f"Errore clock Alpaca, uso calcolo locale: {e}")
        market_open = mh.is_market_open_local()

    # Briefing pre-mercato (09:24–09:26)
    if mh.is_pre_market_briefing_time():
        run_pre_market_briefing()
        return

    # Report chiusura (16:00–16:02)
    if mh.is_market_close_report_time():
        run_market_close_report()
        return

    if not market_open:
        logger.debug("Mercato chiuso, skip ciclo")
        return

    if rm.is_bot_paused():
        logger.info("Bot in pausa (2 SL consecutivi)")
        return

    _capital_cache = _get_current_capital()
    logger.info(f"Ciclo orario — capitale: ${_capital_cache:.2f}")

    # Scarica dati SPY 1h per VIX proxy (usati da tutti gli asset)
    df_spy_1h = ac.get_bars_1h("SPY", bars=5)

    for symbol in ASSETS:
        try:
            _process_asset(symbol, df_spy_1h)
        except Exception as e:
            logger.error(f"[{symbol}] Errore non gestito nel ciclo: {e}")
            tg.send_error(f"[{symbol}] Errore ciclo: {e}")


def _process_asset(symbol: str, df_spy_1h) -> None:
    # 1. Controlla sempre lo stato degli ordini aperti
    om.check_open_orders_status(symbol)

    df_1h    = ac.get_bars_1h(symbol, bars=200)
    df_daily = ac.get_bars_daily(symbol, bars=250)

    if df_1h.empty or df_daily.empty:
        logger.warning(f"[{symbol}] Dati insufficienti, skip")
        return

    pos       = pm.get_position(symbol)
    is_active = pos.get("active", False)
    entry_px  = float(pos["entry_price"]) if is_active and pos.get("entry_price") else None
    tp1_hit   = pos.get("tp1_hit", False)

    sig = st.generate_signal(
        symbol=symbol,
        df_1h=df_1h,
        df_daily=df_daily,
        df_spy_1h=df_spy_1h if symbol != "SPY" else None,
        existing_entry_price=entry_px,
        tp1_hit=tp1_hit,
    )

    logger.info(f"[{symbol}] {sig.signal} | RSI={sig.rsi:.1f} | close={sig.close:.2f} | {sig.reason}")

    if sig.signal == "SELL" and is_active:
        _handle_sell_signal(symbol, sig, pos)

    elif sig.signal == "BUY" and not is_active:
        cooldown_s = pm.seconds_since_close(symbol)
        can_open, reason = rm.can_open_position(symbol, cooldown_s)
        if can_open:
            logger.info(f"[{symbol}] Apertura posizione")
            om.open_new_position(symbol, sig.close, _capital_cache)
        else:
            logger.debug(f"[{symbol}] BUY bloccato: {reason}")


def _handle_sell_signal(symbol: str, sig, pos: dict) -> None:
    reason = sig.sell_reason or "signal"

    if reason == "stop_loss":
        om.handle_stop_loss(symbol, sig.close)

    elif reason == "tp1":
        om.handle_tp1(symbol)

    elif reason in ("tp2", "rsi_overbought", "macd_bearish"):
        # Chiude tutto a mercato per RSI/MACD; TP2 gestito via ordine limit già piazzato
        if reason == "tp2":
            return  # gestito da check_open_orders_status
        entry = float(pos.get("entry_price", sig.close))
        om.close_position_market(symbol, reason=sig.reason)
        profit = (sig.close - entry) * float(pos.get("shares", 0))
        if profit >= 0:
            rm.record_profitable_trade()
        else:
            rm.record_stop_loss()


# ── Avvio ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info(f"=== Stock Trading Bot v{VERSION} avviato ===")
    tg.send_startup(VERSION)

    # Esegui subito un primo ciclo
    run_hourly_cycle()

    # Schedule ogni ora (00 minuti di ogni ora)
    schedule.every().hour.at(":00").do(run_hourly_cycle)

    # Schedule controllo extra a :25 e :55 (per briefing/chiusura)
    schedule.every().hour.at(":25").do(run_hourly_cycle)
    schedule.every().hour.at(":55").do(run_hourly_cycle)

    logger.info("Loop avviato. Ctrl+C per fermare.")
    while True:
        try:
            schedule.run_pending()
            time.sleep(30)
        except KeyboardInterrupt:
            logger.info("Bot fermato dall'utente")
            tg.send_generic("🛑 Bot fermato manualmente")
            break
        except Exception as e:
            logger.error(f"Errore loop principale: {e}")
            tg.send_error(f"Errore loop: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
