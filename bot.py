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

# Evita di rispedire la notifica "mercato chiuso" ad ogni ciclo
_market_closed_notified: bool = False


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

def _market_closed_reason() -> str:
    """Ritorna una stringa leggibile sul motivo per cui il mercato è chiuso."""
    now = mh.now_et()
    if now.weekday() == 5:
        return "weekend (sabato)"
    if now.weekday() == 6:
        return "weekend (domenica)"
    if mh.is_holiday(now.date()):
        return "festività NYSE"
    t = now.time()
    from datetime import time as dtime
    if t < dtime(9, 30):
        mins = mh.minutes_to_open()
        return f"pre-market (apertura tra {mins} min)"
    return "post-market (chiuso dopo le 16:00 ET)"


def _notify_market_closed(reason: str, next_open: str) -> None:
    """Manda la notifica solo la prima volta, poi tace fino alla riapertura."""
    global _market_closed_notified
    if not _market_closed_notified:
        tg.send_generic(
            f"😴 Mercato chiuso — {reason}\n"
            f"Prossima apertura: {next_open}\n"
            f"Il bot è attivo e attende in silenzio."
        )
        _market_closed_notified = True


def run_hourly_cycle() -> None:
    global _capital_cache, _market_closed_notified

    if not mh.is_trading_day():
        reason  = _market_closed_reason()
        next_td = mh.next_trading_day()
        logger.debug(f"Giorno non lavorativo: {reason}, skip")
        _notify_market_closed(reason, next_td.strftime("%A %d/%m") + " 09:30 ET")
        return

    # Verifica mercato aperto tramite Alpaca clock (più affidabile per festività)
    try:
        market_open = ac.is_market_open()
    except Exception as e:
        logger.warning(f"Errore clock Alpaca, uso calcolo locale: {e}")
        market_open = mh.is_market_open_local()

    # Briefing pre-mercato (09:24–09:26)
    if mh.is_pre_market_briefing_time():
        _market_closed_notified = False
        run_pre_market_briefing()
        return

    # Report chiusura (16:00–16:02)
    if mh.is_market_close_report_time():
        run_market_close_report()
        return

    if not market_open:
        reason = _market_closed_reason()
        logger.debug(f"Mercato chiuso ({reason}), skip ciclo")
        _notify_market_closed(reason, "oggi 09:30 ET")
        return

    # Mercato aperto: resetta il flag così alla prossima chiusura notifica di nuovo
    _market_closed_notified = False

    if rm.is_bot_paused():
        logger.info("Bot in pausa (2 SL consecutivi)")
        tg.send_generic("⏸ Bot in pausa (2 SL consecutivi). Riprende domani 09:25 ET.")
        return

    _capital_cache = _get_current_capital()
    logger.info(f"Ciclo orario — capitale: ${_capital_cache:.2f}")

    # P&L di giornata: confronto con capitale iniziale configurato
    pnl_today     = float(_capital_cache) - float(rm.CAPITALE_TOTALE)
    pnl_today_pct = pnl_today / float(rm.CAPITALE_TOTALE) * 100 if rm.CAPITALE_TOTALE else 0

    # Ore al close (mercato chiude alle 16:00 ET)
    now_et        = mh.now_et()
    from datetime import time as dtime
    close_dt      = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    mins_to_close = max(0, int((close_dt - now_et).total_seconds() / 60))

    # Scarica dati SPY 1h per VIX proxy (usati da tutti gli asset)
    df_spy_1h = ac.get_bars_1h("SPY", bars=5)

    cycle_results: list[dict] = []
    for symbol in ASSETS:
        try:
            result = _process_asset(symbol, df_spy_1h)
            if result:
                cycle_results.append(result)
        except Exception as e:
            logger.error(f"[{symbol}] Errore non gestito nel ciclo: {e}")
            tg.send_error(f"[{symbol}] Errore ciclo: {e}")

    if cycle_results:
        cycle_time = now_et.strftime("%H:%M ET")
        tg.send_analysis_cycle(
            cycle_time=cycle_time,
            capital=float(_capital_cache),
            pnl_today=pnl_today,
            pnl_today_pct=pnl_today_pct,
            mins_to_close=mins_to_close,
            results=cycle_results,
        )


def _process_asset(symbol: str, df_spy_1h) -> dict | None:
    # 1. Controlla sempre lo stato degli ordini aperti
    om.check_open_orders_status(symbol)

    df_1h    = ac.get_bars_1h(symbol, bars=200)
    df_daily = ac.get_bars_daily(symbol, bars=250)

    if df_1h.empty or df_daily.empty:
        logger.warning(f"[{symbol}] Dati insufficienti, skip")
        return None

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

    block_reason = ""

    if sig.signal == "SELL" and is_active:
        _handle_sell_signal(symbol, sig, pos)

    elif sig.signal == "BUY" and not is_active:
        cooldown_s = pm.seconds_since_close(symbol)
        can_open, reason = rm.can_open_position(symbol, cooldown_s)
        if can_open:
            logger.info(f"[{symbol}] Apertura posizione")
            om.open_new_position(symbol, sig.close, _capital_cache)
        else:
            block_reason = reason
            logger.debug(f"[{symbol}] BUY bloccato: {reason}")

    unrealized_pct = None
    ema50_dist_pct = None
    next_sl        = None
    next_tp        = None

    if sig.ema50 > 0:
        ema50_dist_pct = (sig.close - sig.ema50) / sig.ema50 * 100

    if is_active and entry_px:
        unrealized_pct = (sig.close - entry_px) / entry_px * 100
        pos_data = pm.get_position(symbol)
        if pos_data.get("tp1_hit"):
            next_sl = pos_data.get("sl")   # breakeven
            next_tp = pos_data.get("tp2")
        else:
            next_sl = pos_data.get("sl")
            next_tp = pos_data.get("tp1")

    return {
        "symbol":        symbol,
        "signal":        sig.signal,
        "close":         sig.close,
        "rsi":           sig.rsi,
        "ema50":         sig.ema50,
        "ema50_ok":      sig.close > sig.ema50,
        "ema50_dist_pct": ema50_dist_pct,
        "macd_hist":     sig.macd_hist,
        "macd_bull":     sig.macd_hist > 0 or sig.macd_bullish_cross,
        "vol_ratio":     sig.volume_ratio,
        "active":        is_active,
        "unrealized_pct": unrealized_pct,
        "next_sl":       next_sl,
        "next_tp":       next_tp,
        "block_reason":  block_reason,
    }


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
