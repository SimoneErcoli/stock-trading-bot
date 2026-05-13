"""
Gestione fuso orario ET, festività USA e verifica stato mercato.
Usa sia il clock Alpaca che calcoli locali per massima affidabilità.
"""

from datetime import datetime, date, time
from zoneinfo import ZoneInfo
from loguru import logger

ET = ZoneInfo("America/New_York")

# Festività NYSE 2025-2026 (date fisse e mobili precompilate)
NYSE_HOLIDAYS = {
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 20),  # MLK Day
    date(2025, 2, 17),  # Presidents' Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),   # Independence Day
    date(2025, 9, 1),   # Labor Day
    date(2025, 11, 27), # Thanksgiving
    date(2025, 12, 25), # Christmas
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
}

MARKET_OPEN  = time(9, 30)
MARKET_CLOSE = time(16, 0)


def now_et() -> datetime:
    return datetime.now(ET)


def today_et() -> date:
    return now_et().date()


def is_holiday(d: date | None = None) -> bool:
    return (d or today_et()) in NYSE_HOLIDAYS


def is_weekend(d: date | None = None) -> bool:
    return (d or today_et()).weekday() >= 5  # 5=Sat, 6=Sun


def is_trading_day(d: date | None = None) -> bool:
    return not is_weekend(d) and not is_holiday(d)


def is_market_open_local() -> bool:
    """Verifica orario locale senza chiamare Alpaca (fallback veloce)."""
    now = now_et()
    if not is_trading_day(now.date()):
        return False
    return MARKET_OPEN <= now.time() < MARKET_CLOSE


def is_last_trading_hour() -> bool:
    """True tra 15:00 e 16:00 ET (no nuovi ingressi)."""
    t = now_et().time()
    return time(15, 0) <= t < MARKET_CLOSE


def is_friday_afternoon() -> bool:
    """True venerdì dopo le 14:00 ET (nessun nuovo ingresso)."""
    now = now_et()
    return now.weekday() == 4 and now.time() >= time(14, 0)


def minutes_to_open() -> int:
    """Minuti all'apertura del mercato. Negativo se già aperto."""
    now = now_et()
    open_dt = now.replace(hour=9, minute=30, second=0, microsecond=0)
    delta = (open_dt - now).total_seconds() / 60
    return int(delta)


def next_trading_day() -> date:
    """Ritorna il prossimo giorno di mercato."""
    d = today_et()
    from datetime import timedelta
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def is_pre_market_briefing_time() -> bool:
    """True dalle 09:24 alle 09:26 ET (finestra briefing)."""
    t = now_et().time()
    return time(9, 24) <= t <= time(9, 26)


def is_market_close_report_time() -> bool:
    """True dalle 16:00 alle 16:02 ET (finestra report chiusura)."""
    t = now_et().time()
    return time(16, 0) <= t <= time(16, 2)


def format_et(dt: datetime | None = None) -> str:
    """Formatta datetime in stringa leggibile ET."""
    dt = dt or now_et()
    return dt.strftime("%d %B %Y alle %H:%M ET")
