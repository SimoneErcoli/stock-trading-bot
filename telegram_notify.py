"""
Tutti i messaggi Telegram del bot.
Usa requests direttamente (sync) per semplicità nel contesto non-async.
"""

import os
from datetime import date

import requests
from loguru import logger

_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "")


def _send(text: str) -> None:
    token = _token()
    chat  = _chat_id()
    if not token or not chat:
        logger.warning("Telegram non configurato (BOT_TOKEN o CHAT_ID mancante)")
        return
    url = _BASE.format(token=token)
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if not resp.ok:
            logger.warning(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
    except requests.RequestException as e:
        logger.error(f"Errore invio Telegram: {e}")


def send_generic(text: str) -> None:
    _send(text)


def send_error(msg: str) -> None:
    _send(f"⚠️ ERRORE BOT\n{msg}")


# ── Messaggi strutturati ───────────────────────────────────────────────────────

def send_pre_market_briefing(
    assets: list[dict],
    portfolio_value: float,
    open_positions: list[str],
    potential_setups: list[str],
    today: date,
) -> None:
    day_str = today.strftime("%-d %B %Y")
    asset_lines = "\n".join(
        f"{a['symbol']}: ${a['price']:.2f} | RSI: {a['rsi']:.1f} | Trend: {a['trend']}"
        for a in assets
    )
    open_pos_str = ", ".join(open_positions) if open_positions else "Nessuna"
    setups_str   = ", ".join(potential_setups) if potential_setups else "Nessuno"

    msg = (
        f"🌅 <b>Briefing pre-mercato — {day_str}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 <b>Situazione asset:</b>\n{asset_lines}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💼 Portafoglio: <b>${portfolio_value:.2f}</b>\n"
        f"📍 Posizioni aperte: {open_pos_str}\n"
        f"🎯 Setup potenziali oggi: {setups_str}\n"
        f"Mercato apre tra 5 minuti."
    )
    _send(msg)


def send_order_sent(
    symbol: str,
    limit_price: float,
    qty: float,
    size_usd: float,
    sl_price: float,
    tp1_price: float,
    order_id: str = "—",
) -> None:
    sl_pct  = (sl_price  / limit_price - 1) * 100
    tp1_pct = (tp1_price / limit_price - 1) * 100
    msg = (
        f"⏳ <b>ORDINE INVIATO — {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Tipo: Limit Buy\n"
        f"Prezzo limit: <b>${limit_price:.2f}</b>\n"
        f"Quantità: {qty:.4f} azioni (${size_usd:.2f})\n"
        f"Order ID: <code>{order_id}</code>\n"
        f"SL automatico: ${sl_price:.2f} ({sl_pct:.1f}%)\n"
        f"TP1 automatico: ${tp1_price:.2f} (+{tp1_pct:.1f}%)\n"
        f"In attesa di esecuzione…"
    )
    _send(msg)


def send_position_opened(
    symbol: str,
    pos: dict,
    signal_rsi: float,
    above_ema50: bool,
    macd_bull: bool,
    vol_ratio: float,
) -> None:
    entry  = float(pos["entry_price"])
    shares = float(pos["shares"])
    size   = float(pos["size_usd"])
    sl     = float(pos["sl"])
    tp1    = float(pos["tp1"])
    tp2    = float(pos["tp2"])
    sl_pct  = (sl  / entry - 1) * 100
    tp1_pct = (tp1 / entry - 1) * 100
    tp2_pct = (tp2 / entry - 1) * 100

    ema_icon  = "✅" if above_ema50 else "❌"
    macd_icon = "✅" if macd_bull   else "❌"
    vol_icon  = "✅" if vol_ratio >= 1.3 else "❌"

    msg = (
        f"🟢 <b>POSIZIONE APERTA — {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"✅ Eseguito a <b>${entry:.2f}</b>\n"
        f"📦 Quantità: {shares:.4f} azioni\n"
        f"💵 Valore: ${size:.2f}\n"
        f"🛡 Stop Loss: ${sl:.2f} ({sl_pct:.1f}%)\n"
        f"🎯 TP1: ${tp1:.2f} (+{tp1_pct:.1f}%)\n"
        f"🎯 TP2: ${tp2:.2f} (+{tp2_pct:.1f}%)\n"
        f"━━━━━━━━━━━━━━━\n"
        f"RSI 1h: {signal_rsi:.1f}\n"
        f"EMA50: sopra {ema_icon}\n"
        f"MACD: {'bullish' if macd_bull else 'neutro'} {macd_icon}\n"
        f"Volume: +{(vol_ratio - 1)*100:.0f}% {vol_icon}\n"
        f"Commissioni: $0.00 (Alpaca zero-fee)"
    )
    _send(msg)


def send_tp1_hit(
    symbol: str,
    tp1_price: float,
    qty_sold: float,
    profit: float,
    breakeven: float,
    tp2_price: float,
    remaining_shares: float,
    remaining_usd: float,
) -> None:
    profit_pct = (profit / (breakeven * qty_sold)) * 100 if breakeven else 0
    msg = (
        f"🟡 <b>TP1 RAGGIUNTO — {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"✅ Venduto 50% a <b>${tp1_price:.2f}</b>\n"
        f"💵 Incassato: ${qty_sold * tp1_price:.2f}\n"
        f"📈 Profitto: +${profit:.2f} (+{profit_pct:.1f}%)\n"
        f"📍 SL spostato al breakeven: ${breakeven:.2f}\n"
        f"🎯 TP2 aperto a ${tp2_price:.2f}\n"
        f"Rimane: {remaining_shares:.4f} azioni (${remaining_usd:.2f})"
    )
    _send(msg)


def send_stop_loss(
    symbol: str,
    fill_price: float,
    loss: float,
    sl_count: int,
) -> None:
    loss_pct = 3.0  # definito fisso dalla strategia
    max_sl   = 2
    msg = (
        f"🔴 <b>STOP LOSS — {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"❌ Chiuso a <b>${fill_price:.2f}</b>\n"
        f"💸 Perdita: -${abs(loss):.2f} (-{loss_pct:.1f}%)\n"
        f"🔢 SL consecutivi: {sl_count}/{max_sl}\n"
        f"⏸ {symbol} in pausa per 2h"
    )
    _send(msg)


def send_pause_alert(loss_total: float) -> None:
    msg = (
        "⚠️ <b>PAUSA ATTIVATA</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"2 stop loss consecutivi.\n"
        f"Perdita sessione: -${abs(loss_total):.2f}\n"
        "Bot in pausa fino a domani.\n"
        "Posizioni aperte mantenute con stop-loss nativi Alpaca attivi.\n"
        "Riprende: domani 09:25 ET"
    )
    _send(msg)


def send_market_close_report(
    portfolio_value: float,
    portfolio_pct: float,
    pnl_today: float,
    closed_trades: list[dict],
    overnight_positions: list[dict],
    next_open_str: str,
    today: date,
) -> None:
    day_str = today.strftime("%-d %B %Y")
    pnl_sign = "+" if pnl_today >= 0 else ""

    trades_lines = ""
    for t in closed_trades:
        icon = "✅" if t["pnl"] >= 0 else "❌"
        sign = "+" if t["pnl"] >= 0 else ""
        trades_lines += f"{icon} {t['symbol']}: {sign}${t['pnl']:.2f} ({sign}{t['pct']:.1f}%)\n"
    if not trades_lines:
        trades_lines = "Nessun trade chiuso\n"

    overnight_lines = ""
    for p in overnight_positions:
        sign  = "+" if p["unrealized_pct"] >= 0 else ""
        check = "✅" if p["trend_ok"] else "⚠️"
        overnight_lines += (
            f"📍 {p['symbol']}: aperta a ${p['entry']:.2f}, "
            f"ora {sign}{p['unrealized_pct']:.1f}% "
            f"(trend daily positivo {check} — {'mantenuta' if p['trend_ok'] else 'valuta chiusura'})\n"
        )
    if not overnight_lines:
        overnight_lines = "Nessuna posizione overnight\n"

    pct_sign = "+" if portfolio_pct >= 0 else ""
    msg = (
        f"🔔 <b>Mercato chiuso — {day_str}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💼 Capitale: <b>${portfolio_value:.2f} ({pct_sign}{portfolio_pct:.2f}%)</b>\n"
        f"📈 P&amp;L oggi: {pnl_sign}${pnl_today:.2f}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Trade chiusi: {len(closed_trades)}\n"
        f"{trades_lines}"
        f"━━━━━━━━━━━━━━━\n"
        f"Posizioni overnight:\n"
        f"{overnight_lines}"
        f"Prossima apertura: {next_open_str}"
    )
    _send(msg)


def send_analysis_cycle(
    cycle_time: str,
    capital: float,
    results: list[dict],
) -> None:
    """
    Inviato al termine di ogni ciclo orario.
    results: lista di dict con chiavi symbol, signal, close, rsi,
             ema50_ok, macd_bull, vol_ratio, active, unrealized_pct, block_reason.
    """
    lines = []
    for r in results:
        symbol   = r["symbol"]
        signal   = r["signal"]
        close    = r["close"]
        rsi      = r["rsi"]
        active   = r.get("active", False)
        unreal   = r.get("unrealized_pct")
        blocked  = r.get("block_reason", "")

        if signal == "BUY" and not blocked:
            sig_icon = "🟢 BUY"
        elif signal == "BUY" and blocked:
            sig_icon = f"🔵 BUY bloccato"
        elif signal == "SELL":
            sig_icon = "🔴 SELL"
        else:
            sig_icon = "⚪ HOLD"

        ema_icon  = "✅" if r.get("ema50_ok")  else "❌"
        macd_icon = "✅" if r.get("macd_bull") else "❌"
        vol       = r.get("vol_ratio", 1.0)
        vol_icon  = "✅" if vol >= 1.3 else "❌"

        pos_line = ""
        if active and unreal is not None:
            sign = "+" if unreal >= 0 else ""
            pos_line = f" | pos: {sign}{unreal:.1f}%"

        block_line = f"\n  ↳ {blocked}" if blocked else ""

        lines.append(
            f"<b>{symbol}</b> {sig_icon} | ${close:.2f} | RSI {rsi:.1f}"
            f" | EMA {ema_icon} MACD {macd_icon} Vol {vol_icon}{pos_line}"
            f"{block_line}"
        )

    body = "\n".join(lines) if lines else "Nessun dato"
    msg = (
        f"🔍 <b>Analisi {cycle_time}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{body}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💼 Capitale: ${capital:.2f}"
    )
    _send(msg)


def send_startup(version: str = "1.0") -> None:
    _send(f"🤖 <b>Bot avviato</b> (v{version})\nMonitoro: SPY, QQQ, IWM")
