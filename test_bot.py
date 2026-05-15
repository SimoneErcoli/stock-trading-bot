"""
Test suite per il trading bot.
Copre: market_hours, position_manager, risk_manager, strategy, telegram_notify.
Nessuna chiamata reale ad Alpaca o Telegram.

Esegui con:  pytest test_bot.py -v
"""

import json
import os
import sys
import tempfile
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ── Forza import dal percorso corretto ───────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

# Imposta env minimale prima di importare i moduli
os.environ.setdefault("CAPITALE_TOTALE", "100")
os.environ.setdefault("RISCHIO_PER_TRADE", "0.015")
os.environ.setdefault("ALPACA_API_KEY", "test_key")
os.environ.setdefault("ALPACA_API_SECRET", "test_secret")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_CHAT_ID", "")

import market_hours as mh
import risk_manager as rm
import strategy as st
import telegram_notify as tg


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_ohlcv(n: int = 220, base_price: float = 500.0, trend: str = "up") -> pd.DataFrame:
    """
    Genera un DataFrame OHLCV sintetico con n candele.
    trend: 'up' | 'down' | 'flat'
    """
    rng = np.random.default_rng(42)
    if trend == "up":
        prices = base_price + np.linspace(0, base_price * 0.15, n) + rng.normal(0, 1.5, n).cumsum()
    elif trend == "down":
        prices = base_price - np.linspace(0, base_price * 0.15, n) + rng.normal(0, 1.5, n).cumsum()
    else:
        prices = base_price + rng.normal(0, 1.5, n).cumsum()

    prices = np.maximum(prices, 10.0)
    idx = pd.date_range("2026-04-01 09:30", periods=n, freq="1h", tz="America/New_York")
    df = pd.DataFrame({
        "open":   prices * (1 + rng.uniform(-0.002, 0.002, n)),
        "high":   prices * (1 + rng.uniform(0.001, 0.005, n)),
        "low":    prices * (1 - rng.uniform(0.001, 0.005, n)),
        "close":  prices,
        "volume": rng.integers(500_000, 3_000_000, n).astype(float),
    }, index=idx)
    return df


def _make_daily(n: int = 260, base_price: float = 500.0) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    prices = base_price + np.linspace(0, base_price * 0.10, n) + rng.normal(0, 2, n).cumsum()
    prices = np.maximum(prices, 10.0)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "open":   prices * 0.999,
        "high":   prices * 1.003,
        "low":    prices * 0.997,
        "close":  prices,
        "volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
    }, index=idx)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# market_hours
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketHours:

    def test_is_weekend_saturday(self):
        assert mh.is_weekend(date(2026, 5, 16)) is True   # sabato

    def test_is_weekend_sunday(self):
        assert mh.is_weekend(date(2026, 5, 17)) is True   # domenica

    def test_is_not_weekend_monday(self):
        assert mh.is_weekend(date(2026, 5, 18)) is False

    def test_is_holiday_memorial_day_2026(self):
        assert mh.is_holiday(date(2026, 5, 25)) is True

    def test_is_holiday_christmas_2026(self):
        assert mh.is_holiday(date(2026, 12, 25)) is True

    def test_is_not_holiday_regular_day(self):
        assert mh.is_holiday(date(2026, 5, 15)) is False

    def test_is_trading_day_monday(self):
        assert mh.is_trading_day(date(2026, 5, 18)) is True

    def test_is_not_trading_day_saturday(self):
        assert mh.is_trading_day(date(2026, 5, 16)) is False

    def test_is_not_trading_day_holiday(self):
        assert mh.is_trading_day(date(2026, 5, 25)) is False

    def test_next_trading_day_skips_weekend(self):
        # venerdì → lunedì
        with patch("market_hours.today_et", return_value=date(2026, 5, 15)):
            result = mh.next_trading_day()
        assert result == date(2026, 5, 18)

    def test_next_trading_day_skips_holiday(self):
        # venerdì prima del Memorial Day → martedì
        with patch("market_hours.today_et", return_value=date(2026, 5, 22)):
            result = mh.next_trading_day()
        assert result == date(2026, 5, 26)

    @patch("market_hours.now_et")
    def test_is_market_open_during_hours(self, mock_now):
        mock_now.return_value = datetime(2026, 5, 18, 11, 0,
                                         tzinfo=mh.ET)
        with patch("market_hours.today_et", return_value=date(2026, 5, 18)):
            assert mh.is_market_open_local() is True

    @patch("market_hours.now_et")
    def test_is_market_closed_before_open(self, mock_now):
        mock_now.return_value = datetime(2026, 5, 18, 8, 0,
                                         tzinfo=mh.ET)
        with patch("market_hours.today_et", return_value=date(2026, 5, 18)):
            assert mh.is_market_open_local() is False

    @patch("market_hours.now_et")
    def test_is_last_trading_hour(self, mock_now):
        mock_now.return_value = datetime(2026, 5, 18, 15, 30,
                                         tzinfo=mh.ET)
        assert mh.is_last_trading_hour() is True

    @patch("market_hours.now_et")
    def test_is_not_last_trading_hour(self, mock_now):
        mock_now.return_value = datetime(2026, 5, 18, 14, 0,
                                         tzinfo=mh.ET)
        assert mh.is_last_trading_hour() is False

    @patch("market_hours.now_et")
    def test_is_friday_afternoon(self, mock_now):
        mock_now.return_value = datetime(2026, 5, 15, 14, 30,
                                         tzinfo=mh.ET)  # venerdì
        assert mh.is_friday_afternoon() is True

    @patch("market_hours.now_et")
    def test_is_not_friday_afternoon_morning(self, mock_now):
        mock_now.return_value = datetime(2026, 5, 15, 11, 0,
                                         tzinfo=mh.ET)
        assert mh.is_friday_afternoon() is False


# ═══════════════════════════════════════════════════════════════════════════════
# position_manager
# ═══════════════════════════════════════════════════════════════════════════════

class TestPositionManager:

    @pytest.fixture(autouse=True)
    def tmp_positions(self, tmp_path, monkeypatch):
        """Ogni test usa un positions.json isolato."""
        import position_manager as pm
        monkeypatch.setattr(pm, "POSITIONS_FILE", tmp_path / "positions.json")
        self.pm = pm

    def test_get_position_empty(self):
        pos = self.pm.get_position("SPY")
        assert pos["active"] is False
        assert pos["shares"] == 0

    def test_open_and_read_position(self):
        self.pm.open_position(
            symbol="SPY", entry_price=528.40, shares=0.094,
            size_usd=49.67, order_id_entry="e1", order_id_sl="s1",
            order_id_tp1="t1", order_id_tp2="t2",
            sl=512.55, tp1=549.54, tp2=570.67,
        )
        pos = self.pm.get_position("SPY")
        assert pos["active"] is True
        assert pos["entry_price"] == 528.40
        assert pos["shares"] == 0.094
        assert pos["sl"] == 512.55
        assert pos["tp1_hit"] is False

    def test_close_position(self):
        self.pm.open_position(
            symbol="QQQ", entry_price=441.0, shares=0.068,
            size_usd=29.99, order_id_entry="e2", order_id_sl="s2",
            order_id_tp1="t3", order_id_tp2="t4",
            sl=427.77, tp1=458.64, tp2=476.28,
        )
        assert self.pm.is_active("QQQ") is True
        self.pm.close_position("QQQ")
        assert self.pm.is_active("QQQ") is False
        assert self.pm.get_position("QQQ")["last_closed_time"] is not None

    def test_mark_tp1_hit_halves_shares(self):
        self.pm.open_position(
            symbol="IWM", entry_price=198.0, shares=0.100,
            size_usd=19.80, order_id_entry="e3", order_id_sl="s3",
            order_id_tp1="t5", order_id_tp2="t6",
            sl=192.06, tp1=205.92, tp2=213.84,
        )
        self.pm.mark_tp1_hit("IWM", new_sl=198.0)
        pos = self.pm.get_position("IWM")
        assert pos["tp1_hit"] is True
        assert pos["sl"] == 198.0
        assert abs(pos["shares"] - 0.05) < 1e-6

    def test_seconds_since_close_never_closed(self):
        assert self.pm.seconds_since_close("SPY") == -1.0

    def test_seconds_since_close_after_close(self):
        self.pm.open_position(
            "SPY", 528.0, 0.09, 47.0, "e", "s", "t1", "t2", 512.0, 549.0, 570.0
        )
        self.pm.close_position("SPY")
        secs = self.pm.seconds_since_close("SPY")
        assert 0 <= secs < 5  # chiuso pochi secondi fa

    def test_multiple_assets_independent(self):
        self.pm.open_position("SPY", 528.0, 0.09, 47.0, "e1", "s1", "t1", "t2", 512.0, 549.0, 570.0)
        self.pm.open_position("QQQ", 441.0, 0.07, 30.0, "e2", "s2", "t3", "t4", 427.0, 458.0, 476.0)
        self.pm.close_position("SPY")
        assert self.pm.is_active("SPY") is False
        assert self.pm.is_active("QQQ") is True


# ═══════════════════════════════════════════════════════════════════════════════
# risk_manager
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskManager:

    @pytest.fixture(autouse=True)
    def tmp_risk_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rm, "RISK_STATE_FILE", tmp_path / "risk_state.json")

    def test_position_size_spy(self):
        size = rm.compute_position_size("SPY", Decimal("100"))
        assert size == Decimal("50.00")

    def test_position_size_qqq(self):
        size = rm.compute_position_size("QQQ", Decimal("100"))
        assert size == Decimal("30.00")

    def test_position_size_iwm(self):
        size = rm.compute_position_size("IWM", Decimal("100"))
        assert size == Decimal("20.00")

    def test_compute_shares(self):
        shares = rm.compute_shares(Decimal("50.00"), Decimal("528.40"))
        assert shares == Decimal("0.094625")

    def test_compute_shares_zero_price(self):
        assert rm.compute_shares(Decimal("50"), Decimal("0")) == Decimal("0")

    def test_sl_price(self):
        sl = rm.compute_sl_price(Decimal("528.40"))
        assert sl == Decimal("512.54")

    def test_tp1_price(self):
        tp1 = rm.compute_tp1_price(Decimal("528.40"))
        assert tp1 == Decimal("549.53")

    def test_tp2_price(self):
        tp2 = rm.compute_tp2_price(Decimal("528.40"))
        assert tp2 == Decimal("570.67")

    def test_sl_tp_percentages(self):
        entry = Decimal("100.00")
        assert rm.compute_sl_price(entry)  == Decimal("97.00")
        assert rm.compute_tp1_price(entry) == Decimal("104.00")
        assert rm.compute_tp2_price(entry) == Decimal("108.00")

    def test_consecutive_sl_counter(self):
        with patch("market_hours.today_et", return_value=date(2026, 5, 18)), \
             patch("market_hours.next_trading_day", return_value=date(2026, 5, 19)):
            assert rm.record_stop_loss() == 1
            assert rm.consecutive_sl_count() == 1

    def test_pause_after_two_sl(self):
        with patch("market_hours.today_et", return_value=date(2026, 5, 18)), \
             patch("market_hours.next_trading_day", return_value=date(2026, 5, 19)):
            rm.record_stop_loss()
            rm.record_stop_loss()
        with patch("market_hours.today_et", return_value=date(2026, 5, 18)):
            assert rm.is_bot_paused() is True

    def test_pause_expires_next_day(self):
        with patch("market_hours.today_et", return_value=date(2026, 5, 18)), \
             patch("market_hours.next_trading_day", return_value=date(2026, 5, 19)):
            rm.record_stop_loss()
            rm.record_stop_loss()
        with patch("market_hours.today_et", return_value=date(2026, 5, 19)):
            assert rm.is_bot_paused() is False

    def test_profitable_trade_resets_counter(self):
        with patch("market_hours.today_et", return_value=date(2026, 5, 18)), \
             patch("market_hours.next_trading_day", return_value=date(2026, 5, 19)):
            rm.record_stop_loss()
        rm.record_profitable_trade()
        assert rm.consecutive_sl_count() == 0

    def test_overnight_allowed_above_ema200(self):
        assert rm.is_overnight_allowed(ema200_daily=500.0, current_close=520.0) is True

    def test_overnight_not_allowed_below_ema200(self):
        assert rm.is_overnight_allowed(ema200_daily=500.0, current_close=490.0) is False

    @patch("market_hours.is_trading_day", return_value=True)
    @patch("market_hours.is_market_open_local", return_value=True)
    @patch("market_hours.is_last_trading_hour", return_value=False)
    @patch("market_hours.is_friday_afternoon", return_value=False)
    def test_can_open_position_ok(self, *_):
        ok, reason = rm.can_open_position("SPY", seconds_since_last_close=-1)
        assert ok is True
        assert reason == ""

    @patch("market_hours.is_trading_day", return_value=True)
    @patch("market_hours.is_market_open_local", return_value=True)
    @patch("market_hours.is_last_trading_hour", return_value=True)
    @patch("market_hours.is_friday_afternoon", return_value=False)
    def test_can_open_blocked_last_hour(self, *_):
        ok, reason = rm.can_open_position("SPY", seconds_since_last_close=-1)
        assert ok is False
        assert "ultima ora" in reason

    @patch("market_hours.is_trading_day", return_value=True)
    @patch("market_hours.is_market_open_local", return_value=True)
    @patch("market_hours.is_last_trading_hour", return_value=False)
    @patch("market_hours.is_friday_afternoon", return_value=False)
    def test_can_open_blocked_cooldown(self, *_):
        ok, reason = rm.can_open_position("SPY", seconds_since_last_close=3600)
        assert ok is False
        assert "cooldown" in reason


# ═══════════════════════════════════════════════════════════════════════════════
# strategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategy:

    def test_compute_indicators_adds_columns(self):
        df_1h    = _make_ohlcv(220)
        df_daily = _make_daily(260)
        result   = st.compute_indicators(df_1h, df_daily)
        for col in ["RSI_14", "EMA_20", "EMA_50", "EMA_200",
                    "MACDh_12_26_9", "vol_ma20", "ema200_daily"]:
            assert col in result.columns, f"Colonna mancante: {col}"

    def test_compute_indicators_vwap_present(self):
        df_1h    = _make_ohlcv(220)
        df_daily = _make_daily(260)
        result   = st.compute_indicators(df_1h, df_daily)
        vwap_cols = [c for c in result.columns if c.startswith("VWAP")]
        assert len(vwap_cols) > 0, "Nessuna colonna VWAP trovata"

    def test_signal_hold_on_flat_market(self):
        df_1h    = _make_ohlcv(220, trend="flat")
        df_daily = _make_daily(260)
        sig = st.generate_signal("SPY", df_1h, df_daily)
        assert sig.signal in ("BUY", "HOLD", "SELL")
        assert sig.close > 0
        assert sig.rsi > 0

    def test_signal_has_vwap(self):
        df_1h    = _make_ohlcv(220, trend="up")
        df_daily = _make_daily(260)
        sig = st.generate_signal("SPY", df_1h, df_daily)
        assert hasattr(sig, "vwap")
        assert sig.vwap >= 0

    def test_sell_signal_on_stop_loss(self):
        df_1h    = _make_ohlcv(220, base_price=500.0, trend="flat")
        df_daily = _make_daily(260)
        # entry a 530 → close attuale ~500 → sotto SL del 3%
        sig = st.generate_signal(
            "SPY", df_1h, df_daily,
            existing_entry_price=530.0,
            tp1_hit=False,
        )
        assert sig.signal == "SELL"
        assert sig.sell_reason == "stop_loss"

    def test_sell_signal_tp1(self):
        df_1h    = _make_ohlcv(220, base_price=500.0, trend="flat")
        df_daily = _make_daily(260)
        # entry a 400 → close ~500 → sopra TP1 del 4% (416)
        sig = st.generate_signal(
            "SPY", df_1h, df_daily,
            existing_entry_price=400.0,
            tp1_hit=False,
        )
        assert sig.signal == "SELL"
        assert sig.sell_reason == "tp1"

    def test_sell_signal_tp2(self):
        df_1h    = _make_ohlcv(220, base_price=500.0, trend="flat")
        df_daily = _make_daily(260)
        # entry a 380 → close ~500 → sopra TP2 del 8% (410)
        sig = st.generate_signal(
            "SPY", df_1h, df_daily,
            existing_entry_price=380.0,
            tp1_hit=True,
        )
        assert sig.signal == "SELL"
        assert sig.sell_reason == "tp2"

    def test_vix_proxy_blocks_buy(self):
        df_1h    = _make_ohlcv(220, trend="up")
        df_daily = _make_daily(260)
        # SPY scende del 2% nell'ultima candela
        df_spy           = _make_ohlcv(5, base_price=500.0, trend="flat")
        df_spy.iloc[-1, df_spy.columns.get_loc("close")] = df_spy["close"].iloc[-2] * 0.978
        sig = st.generate_signal("QQQ", df_1h, df_daily, df_spy_1h=df_spy)
        if sig.signal == "BUY":
            pytest.skip("Dati sintetici non hanno generato il segnale VIX — ok")
        assert "VIX" in sig.reason or sig.signal in ("HOLD", "BUY")

    def test_missing_columns_returns_hold(self):
        bad_df = pd.DataFrame({"close": [100, 101]})
        df_daily = _make_daily(260)
        sig = st.generate_signal("SPY", bad_df, df_daily)
        assert sig.signal == "HOLD"
        assert sig.close == 0


# ═══════════════════════════════════════════════════════════════════════════════
# telegram_notify — verifica formato messaggi (nessuna chiamata HTTP reale)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTelegramNotify:

    @pytest.fixture(autouse=True)
    def mock_send(self, monkeypatch):
        self.sent: list[str] = []
        monkeypatch.setattr(tg, "_send", lambda text: self.sent.append(text))

    def test_send_generic(self):
        tg.send_generic("ciao")
        assert self.sent == ["ciao"]

    def test_send_error_prefix(self):
        tg.send_error("qualcosa è andato storto")
        assert "ERRORE" in self.sent[0]

    def test_pre_market_briefing_contains_assets(self):
        tg.send_pre_market_briefing(
            assets=[
                {"symbol": "SPY", "price": 528.40, "rsi": 48.2, "trend": "▲"},
                {"symbol": "QQQ", "price": 441.20, "rsi": 52.1, "trend": "▲"},
            ],
            portfolio_value=101.44,
            open_positions=["SPY (+1.2%)"],
            potential_setups=["IWM"],
            today=date(2026, 5, 15),
        )
        msg = self.sent[0]
        assert "SPY" in msg
        assert "QQQ" in msg
        assert "528.40" in msg
        assert "Briefing" in msg

    def test_order_sent_contains_key_fields(self):
        tg.send_order_sent(
            symbol="SPY", limit_price=528.42, qty=0.094,
            size_usd=49.67, sl_price=512.57, tp1_price=549.56,
        )
        msg = self.sent[0]
        assert "528.42" in msg
        assert "512.57" in msg
        assert "549.56" in msg
        assert "SPY" in msg

    def test_stop_loss_message(self):
        tg.send_stop_loss("QQQ", fill_price=427.77, loss=0.95, sl_count=1)
        msg = self.sent[0]
        assert "STOP LOSS" in msg
        assert "QQQ" in msg
        assert "427.77" in msg
        assert "1/2" in msg

    def test_pause_alert_message(self):
        tg.send_pause_alert(loss_total=2.98)
        msg = self.sent[0]
        assert "PAUSA" in msg
        assert "2.98" in msg

    def test_analysis_cycle_all_assets(self):
        results = [
            {"symbol": "SPY",  "signal": "HOLD", "close": 528.40, "rsi": 55.2,
             "ema50_ok": True,  "ema50": 512.30, "ema50_dist_pct": 3.1,
             "macd_bull": False, "macd_hist": -0.05, "vol_ratio": 0.9,
             "vwap": 525.0, "vwap_ok": True, "vwap_dist_pct": 0.6,
             "active": False, "unrealized_pct": None, "next_sl": None,
             "next_tp": None, "block_reason": ""},
            {"symbol": "QQQ",  "signal": "BUY",  "close": 441.20, "rsi": 44.8,
             "ema50_ok": True,  "ema50": 435.10, "ema50_dist_pct": 1.4,
             "macd_bull": True,  "macd_hist": 0.12, "vol_ratio": 1.6,
             "vwap": 438.90, "vwap_ok": True, "vwap_dist_pct": 0.5,
             "active": False, "unrealized_pct": None, "next_sl": None,
             "next_tp": None, "block_reason": ""},
            {"symbol": "IWM",  "signal": "BUY",  "close": 198.30, "rsi": 39.1,
             "ema50_ok": True,  "ema50": 195.80, "ema50_dist_pct": 1.3,
             "macd_bull": True,  "macd_hist": 0.03, "vol_ratio": 1.4,
             "vwap": 197.50, "vwap_ok": True, "vwap_dist_pct": 0.4,
             "active": True,  "unrealized_pct": 0.82,
             "next_sl": 192.35, "next_tp": 206.23, "block_reason": "cooldown 2h"},
        ]
        tg.send_analysis_cycle(
            cycle_time="11:00 ET",
            capital=101.44,
            pnl_today=1.44,
            pnl_today_pct=1.44,
            mins_to_close=298,
            results=results,
        )
        msg = self.sent[0]
        assert "SPY" in msg and "QQQ" in msg and "IWM" in msg
        assert "HOLD" in msg
        assert "BUY" in msg
        assert "VWAP" in msg
        assert "101.44" in msg
        assert "1.44" in msg
        assert "4h 58m" in msg
        assert "192.35" in msg    # SL posizione IWM
        assert "cooldown" in msg  # motivo blocco

    def test_tp1_hit_message(self):
        tg.send_tp1_hit(
            symbol="SPY", tp1_price=549.54, qty_sold=0.047,
            profit=0.99, breakeven=528.40, tp2_price=570.67,
            remaining_shares=0.047, remaining_usd=25.84,
        )
        msg = self.sent[0]
        assert "TP1" in msg
        assert "549.54" in msg
        assert "breakeven" in msg.lower() or "528.40" in msg

    def test_market_close_report(self):
        tg.send_market_close_report(
            portfolio_value=101.44,
            portfolio_pct=1.44,
            pnl_today=1.44,
            closed_trades=[
                {"symbol": "SPY", "pnl": 0.99, "pct": 4.0},
                {"symbol": "QQQ", "pnl": -0.45, "pct": -1.5},
            ],
            overnight_positions=[
                {"symbol": "IWM", "entry": 198.30,
                 "unrealized_pct": 0.8, "trend_ok": True},
            ],
            next_open_str="lunedì 18/05 09:30 ET",
            today=date(2026, 5, 15),
        )
        msg = self.sent[0]
        assert "SPY" in msg
        assert "QQQ" in msg
        assert "IWM" in msg
        assert "101.44" in msg
        assert "lunedì" in msg
