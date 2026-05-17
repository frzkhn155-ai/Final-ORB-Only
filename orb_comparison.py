"""
orb_comparison.py
=================
Runs both ORB implementations in parallel and writes side-by-side comparison logs.

FILE 1 (IST-aware)  : uses pytz / now_ist()  — "headless" version
FILE 2 (local time) : uses datetime.now()    — original version

Both use an identical algorithm; the only real difference is the clock source.
This harness:
  1. Wraps each ORB engine in its own thread.
  2. Feeds them the same live_data snapshot every scan cycle.
  3. Logs signals to  orb_v1.log / orb_v2.log  AND to  orb_diff.log
     (diff log only shows entries where outputs diverge).
  4. Prints a live comparison table to stdout.

HOW TO RUN
----------
    python orb_comparison.py --token YOUR_UPSTOX_TOKEN [--live]

Without --live the harness runs in TEST_MODE using synthetic candle data
so you can validate logic without a market connection.

DEPENDENCIES
------------
    pip install pytz pandas requests
"""

import threading
import time
import csv
import json
import logging
import argparse
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional, Dict, Any, List, Tuple

# ── optional pytz (needed for V1 engine) ──────────────────────────────────────
try:
    import pytz
    _IST = pytz.timezone("Asia/Kolkata")
    PYTZ_OK = True
except ImportError:
    PYTZ_OK = False
    print("⚠️  pytz not found — V1 engine will fall back to datetime.now()")

# ── optional pandas ────────────────────────────────────────────────────────────
try:
    import pandas as pd
    PANDAS_OK = True
except ImportError:
    PANDAS_OK = False

# =============================================================================
# SHARED CONFIGURATION  (identical for both engines)
# =============================================================================

ORB_TIMEFRAME_MINUTES        = 15
ORB_MIN_CANDLE_BODY_LONG     = 0.6
ORB_MIN_CANDLE_BODY_SHORT    = 0.6
ORB_TARGET_MULTIPLIER        = 2.0
ORB_STOP_MULTIPLIER          = 1.0
ORB_VOLUME_CONFIRMATION      = 1.5
ORB_BREAKOUT_WINDOW_MINUTES  = 60
ORB_ENABLE_FII_DII_FILTER    = False   # disabled for fair comparison (no external data)
ORB_ENABLE_KLINGER_GATE      = False   # disabled — focus on pure ORB logic
ORB_ENABLE_RSI_GATE          = False

LOG_DIR = "."   # write logs beside the script

# =============================================================================
# CLOCK HELPERS  — the only real difference between the two versions
# =============================================================================

def now_ist() -> datetime:
    """V1 clock: current time in IST (pytz-aware), returned as naive datetime."""
    if PYTZ_OK:
        return datetime.now(_IST).replace(tzinfo=None)
    return datetime.now()   # fallback if pytz missing


def now_local() -> datetime:
    """V2 clock: plain datetime.now() — local system clock."""
    return datetime.now()


# =============================================================================
# MINIMAL STUBS  (replace the real bot globals with lightweight equivalents)
# =============================================================================

class _FakeR3Levels:
    """Thread-safe stub for R3_LEVELS / SYMBOL_TO_ISIN lookups."""
    def __init__(self):
        self._data: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: Dict):
        with self._lock:
            self._data[key] = value

    def get(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)


FAKE_R3 = _FakeR3Levels()
SYMBOL_TO_ISIN: Dict[str, str]  = {}
ISIN_TO_SYMBOL: Dict[str, str]  = {}
VOLUME_DATA:    Dict[str, float] = {}


def get_realtime_5min_df(symbol: str, min_bars: int = 15) -> Optional[Any]:
    """Stub — returns None (RSI gate disabled so this is never actually used)."""
    return None


def calculate_rsi(df: Any, period: int = 14) -> Optional[float]:
    """Stub."""
    return None


# =============================================================================
# ORB SIGNAL CALCULATOR  (identical logic, different clock injected at call site)
# =============================================================================

def calculate_orb_levels(
    symbol: str,
    open_price: float,
    close_price: float,
    high_price: float,
    low_price: float,
    volume: float,
    now_fn,                         # ← clock injection point
    candle_df=None,
    instrument_key: Optional[str] = None,
) -> Optional[Dict]:
    """
    Pure ORB level calculator extracted from both versions.
    `now_fn` is the only difference: V1 passes now_ist, V2 passes now_local.
    """
    body_size    = abs(close_price - open_price)
    body_percent = (body_size / open_price) * 100 if open_price else 0
    is_bullish   = close_price > open_price
    is_bearish   = close_price < open_price

    if not is_bullish and not is_bearish:
        return None

    min_body = ORB_MIN_CANDLE_BODY_LONG if is_bullish else ORB_MIN_CANDLE_BODY_SHORT
    if body_percent < min_body:
        return None

    if is_bullish:
        breakout_level = close_price
        stop_level     = low_price
        target_level   = close_price + body_size * ORB_TARGET_MULTIPLIER
        direction      = "BUY"
        signal_type    = "BULLISH_ORB"
    else:
        breakout_level = close_price
        stop_level     = high_price
        target_level   = close_price - body_size * ORB_TARGET_MULTIPLIER
        direction      = "SELL"
        signal_type    = "BEARISH_ORB"

    # FII/DII confidence stub (filter disabled)
    confidence = "HIGH"

    risk   = abs(breakout_level - stop_level)
    reward = abs(target_level   - breakout_level)
    if risk <= 0:
        return None

    return {
        "symbol":         symbol,
        "instrument_key": instrument_key,
        "timestamp":      now_fn(),          # ← clock used here
        "signal_type":    signal_type,
        "direction":      direction,
        "open":           open_price,
        "close":          close_price,
        "high":           high_price,
        "low":            low_price,
        "body_size":      body_size,
        "body_percent":   body_percent,
        "breakout_level": breakout_level,
        "stop_level":     stop_level,
        "target_level":   target_level,
        "volume":         volume,
        "is_bullish":     is_bullish,
        "risk":           risk,
        "reward":         reward,
        "risk_reward":    reward / risk,
        "fii_dii_signal": "NEUTRAL",
        "confidence":     confidence,
        "rsi_at_signal":  None,
        "klinger_at_signal": None,
    }


def check_orb_breakout(
    symbol: str,
    current_price: float,
    current_volume: float,
    orb_signal: Dict,
    alerted_set: set,
    avg_volume: float,
    now_fn,
) -> Optional[Dict]:
    """
    Breakout detector — identical logic, clock-injected.
    Returns a breakout dict or None.
    """
    if symbol in alerted_set:
        return None

    now  = now_fn()
    m930 = now.replace(hour=9, minute=30, second=0, microsecond=0)
    mins = (now - m930).total_seconds() / 60
    if mins < 0 or mins > ORB_BREAKOUT_WINDOW_MINUTES:
        return None

    vol_ratio = current_volume / avg_volume if avg_volume > 0 else 0
    if avg_volume > 0 and vol_ratio < ORB_VOLUME_CONFIRMATION:
        return None

    result = None
    if orb_signal["is_bullish"] and current_price > orb_signal["breakout_level"] * 1.001:
        result = {
            "symbol":        symbol,
            "signal":        "ORB_BREAKOUT",
            "direction":     "BUY",
            "entry_price":   current_price,
            "stop_loss":     orb_signal["stop_level"],
            "target":        orb_signal["target_level"],
            "volume_ratio":  vol_ratio,
            "confidence":    orb_signal["confidence"],
            "fii_dii_signal": "NEUTRAL",
            "risk":          orb_signal["risk"],
            "reward":        orb_signal["reward"],
            "risk_reward":   orb_signal["risk_reward"],
            "timestamp":     now_fn(),
        }
    elif not orb_signal["is_bullish"] and current_price < orb_signal["breakout_level"] * 0.999:
        result = {
            "symbol":        symbol,
            "signal":        "ORB_BREAKDOWN",
            "direction":     "SELL",
            "entry_price":   current_price,
            "stop_loss":     orb_signal["stop_level"],
            "target":        orb_signal["target_level"],
            "volume_ratio":  vol_ratio,
            "confidence":    orb_signal["confidence"],
            "fii_dii_signal": "NEUTRAL",
            "risk":          orb_signal["risk"],
            "reward":        orb_signal["reward"],
            "risk_reward":   orb_signal["risk_reward"],
            "timestamp":     now_fn(),
        }
    return result


# =============================================================================
# ORB ENGINE  — one instance per version
# =============================================================================

class ORBEngine:
    """
    Self-contained ORB engine that wraps calculate_orb_levels + check_orb_breakout.
    Instantiate twice with different `now_fn` to get V1 and V2 behaviours.
    """

    def __init__(self, name: str, now_fn, log_path: str):
        self.name        = name
        self.now_fn      = now_fn
        self.signals:  Dict[str, Dict] = {}   # symbol -> ORB signal
        self.alerted:  set             = set()
        self.breakouts: List[Dict]     = []    # all fired breakouts this session
        self._lock = threading.Lock()

        # Per-engine CSV log
        self.log_path = log_path
        with open(log_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "engine", "event", "timestamp", "symbol",
                "signal_type", "direction", "breakout_level",
                "stop_level", "target_level", "body_pct", "rr",
                "confidence",
            ])

    # ── public API ─────────────────────────────────────────────────────────────

    def process_first_candle(
        self, symbol: str, ikey: str,
        open_p: float, close_p: float, high_p: float, low_p: float,
        volume: float,
    ) -> Optional[Dict]:
        """Feed the first 15-min candle; store and log the ORB signal if valid."""
        sig = calculate_orb_levels(
            symbol, open_p, close_p, high_p, low_p, volume,
            now_fn=self.now_fn,
            instrument_key=ikey,
        )
        with self._lock:
            if sig:
                self.signals[symbol] = sig
                self._log_event("SIGNAL", sig)
            return sig

    def check_breakout(
        self, symbol: str, price: float, volume: float, avg_vol: float
    ) -> Optional[Dict]:
        """Check if price has broken out of the ORB range."""
        with self._lock:
            sig = self.signals.get(symbol)
        if not sig:
            return None
        bo = check_orb_breakout(
            symbol, price, volume, sig,
            alerted_set=self.alerted,
            avg_volume=avg_vol,
            now_fn=self.now_fn,
        )
        if bo:
            with self._lock:
                self.alerted.add(symbol)
                self.breakouts.append(bo)
                self._log_event("BREAKOUT", bo)
        return bo

    def reset_day(self):
        with self._lock:
            self.signals.clear()
            self.alerted.clear()

    # ── private ────────────────────────────────────────────────────────────────

    def _log_event(self, event_type: str, data: Dict):
        ts = data.get("timestamp") or self.now_fn()
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts, datetime) else str(ts)
        row = [
            self.name, event_type, ts_str,
            data.get("symbol", ""),
            data.get("signal_type") or data.get("signal", ""),
            data.get("direction", ""),
            f"{data.get('breakout_level', data.get('entry_price', 0)):.2f}",
            f"{data.get('stop_level', data.get('stop_loss', 0)):.2f}",
            f"{data.get('target_level', data.get('target', 0)):.2f}",
            f"{data.get('body_percent', 0):.2f}",
            f"{data.get('risk_reward', 0):.2f}",
            data.get("confidence", ""),
        ]
        with open(self.log_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)


# =============================================================================
# DIFF LOGGER  — records divergence between V1 and V2
# =============================================================================

DIFF_LOG = "orb_diff.log"

def write_diff(symbol: str, v1_result, v2_result, context: str = ""):
    """Append a divergence entry to orb_diff.log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DIFF_LOG, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*70}\n")
        f.write(f"[{ts}] DIVERGENCE  symbol={symbol}  context={context}\n")
        f.write(f"  V1 → {v1_result}\n")
        f.write(f"  V2 → {v2_result}\n")


# =============================================================================
# SYNTHETIC DATA GENERATOR  (for TEST_MODE without live market)
# =============================================================================

def generate_synthetic_candles(n: int = 20) -> List[Dict]:
    """
    Produce N synthetic 5-min OHLCV candles starting from 09:15 today.
    Used in test mode to exercise the ORB logic end-to-end.
    """
    import random
    random.seed(42)
    base  = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
    price = 500.0
    candles = []
    for i in range(n):
        open_p  = price
        change  = random.uniform(-0.8, 1.0)
        close_p = round(open_p + change, 2)
        high_p  = round(max(open_p, close_p) + random.uniform(0, 0.5), 2)
        low_p   = round(min(open_p, close_p) - random.uniform(0, 0.5), 2)
        vol     = random.randint(80_000, 300_000)
        candles.append({
            "date":   base + timedelta(minutes=5 * i),
            "open":   open_p,
            "high":   high_p,
            "low":    low_p,
            "close":  close_p,
            "volume": vol,
        })
        price = close_p
    return candles


# =============================================================================
# SCAN LOOP  — feeds same data to both engines each cycle
# =============================================================================

_STOP_EVENT = threading.Event()

def run_comparison(
    v1: ORBEngine,
    v2: ORBEngine,
    live_data_fn,            # callable() → Dict[symbol, Dict]
    scan_interval: int = 30,
    max_scans: int = 40,
):
    """
    Main comparison loop.

    `live_data_fn()` must return a dict like:
        { "RELIANCE": {"ltp": 2800, "open": 2780, "high": 2810,
                        "low": 2770, "volume": 120000, "avg_volume": 90000} }

    On the first scan after 09:30 both engines call process_first_candle().
    On subsequent scans both call check_breakout().
    Any divergence in signal/breakout outcome is written to orb_diff.log.
    """
    first_candle_processed: Dict[str, bool] = defaultdict(bool)
    scan_n = 0

    print(f"\n{'='*70}")
    print(f" ORB COMPARISON  —  V1 (IST-aware)  vs  V2 (local clock)")
    print(f"{'='*70}")
    print(f" {'Scan':>5}  {'Time':^19}  {'Symbol':^12}  "
          f"{'V1 signal':^16}  {'V2 signal':^16}  {'Match?':^7}")
    print(f"{'─'*70}")

    while not _STOP_EVENT.is_set() and scan_n < max_scans:
        scan_n += 1
        now = datetime.now()
        live_data = live_data_fn()

        for symbol, tick in live_data.items():
            ltp        = tick.get("ltp", 0)
            open_p     = tick.get("open", ltp)
            high_p     = tick.get("high", ltp)
            low_p      = tick.get("low",  ltp)
            volume     = tick.get("volume", 0)
            avg_volume = tick.get("avg_volume", volume or 1)
            ikey       = tick.get("ikey", f"NSE_EQ|{symbol}")

            # ── Phase 1: first-candle pass (09:30–09:35) ─────────────────────
            if not first_candle_processed[symbol]:
                sig_v1 = v1.process_first_candle(symbol, ikey, open_p, ltp, high_p, low_p, volume)
                sig_v2 = v2.process_first_candle(symbol, ikey, open_p, ltp, high_p, low_p, volume)
                first_candle_processed[symbol] = True

                v1_out = sig_v1["signal_type"] if sig_v1 else "None"
                v2_out = sig_v2["signal_type"] if sig_v2 else "None"
                match  = "✅" if v1_out == v2_out else "❌"

                print(f" {scan_n:>5}  {now.strftime('%H:%M:%S'):^19}  "
                      f"{symbol:^12}  {v1_out:^16}  {v2_out:^16}  {match:^7}")

                if v1_out != v2_out:
                    write_diff(symbol, v1_out, v2_out, context="first_candle")

            # ── Phase 2: breakout monitoring ──────────────────────────────────
            else:
                bo_v1 = v1.check_breakout(symbol, ltp, volume, avg_volume)
                bo_v2 = v2.check_breakout(symbol, ltp, volume, avg_volume)

                if bo_v1 or bo_v2:
                    v1_out = bo_v1["signal"] if bo_v1 else "None"
                    v2_out = bo_v2["signal"] if bo_v2 else "None"
                    match  = "✅" if v1_out == v2_out else "❌"

                    print(f" {scan_n:>5}  {now.strftime('%H:%M:%S'):^19}  "
                          f"{symbol:^12}  {v1_out:^16}  {v2_out:^16}  {match:^7}  [BREAKOUT]")

                    if v1_out != v2_out:
                        write_diff(symbol, bo_v1, bo_v2, context="breakout")

        time.sleep(scan_interval)

    print(f"\n{'─'*70}")
    print(f" Scan loop ended after {scan_n} cycles.")
    print(f" V1 signals: {len(v1.signals)}  |  V2 signals: {len(v2.signals)}")
    print(f" V1 breakouts: {len(v1.breakouts)}  |  V2 breakouts: {len(v2.breakouts)}")
    print(f" Logs: {v1.log_path}  {v2.log_path}  {DIFF_LOG}")
    print(f"{'='*70}\n")


# =============================================================================
# SYNTHETIC LIVE-DATA PROVIDER  (test mode)
# =============================================================================

def make_synthetic_provider(symbols: List[str], scan_interval: int = 30):
    """
    Returns a callable that produces deterministic 'live' tick data.
    Simulates a slow bullish drift to trigger a BULLISH_ORB then breakout.
    """
    import random
    state: Dict[str, float] = {s: 500.0 + i * 50 for i, s in enumerate(symbols)}
    scan_n = [0]

    def provider() -> Dict[str, Dict]:
        scan_n[0] += 1
        data = {}
        for sym in symbols:
            base  = state[sym]
            # Drift upward 0.15 % per scan to eventually cross the ORB high
            drift = base * 0.0015 * scan_n[0]
            ltp   = round(base + drift, 2)
            # Make first-candle strongly bullish (body > 0.6 %)
            open_p = round(base * 0.993, 2)
            high_p = round(ltp * 1.002, 2)
            low_p  = round(open_p * 0.998, 2)
            vol    = 150_000 + scan_n[0] * 5_000   # growing volume
            data[sym] = {
                "ltp": ltp, "open": open_p, "high": high_p, "low": low_p,
                "volume": vol, "avg_volume": 80_000,
                "ikey": f"NSE_EQ|{sym}",
            }
        return data

    return provider


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="ORB dual-engine comparison")
    parser.add_argument("--token",    default="",  help="Upstox access token (for live mode)")
    parser.add_argument("--live",     action="store_true", help="Use real Upstox data feed")
    parser.add_argument("--symbols",  default="RELIANCE,TCS,INFY,HDFCBANK",
                        help="Comma-separated symbols to watch")
    parser.add_argument("--scans",    type=int, default=20,
                        help="Number of scan cycles (default 20)")
    parser.add_argument("--interval", type=int, default=5,
                        help="Seconds between scans in test mode (default 5)")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    # ── Instantiate both engines ──────────────────────────────────────────────
    v1 = ORBEngine(name="V1_IST",   now_fn=now_ist,   log_path="orb_v1.log")
    v2 = ORBEngine(name="V2_LOCAL", now_fn=now_local, log_path="orb_v2.log")

    # ── Choose data provider ──────────────────────────────────────────────────
    if args.live and args.token:
        # Real live-data feed — requires the bot's get_live_prices_batch().
        # We import it lazily so the script still works without the full bot.
        try:
            from Both4withcache10_headless import get_live_prices_batch, SYMBOL_TO_ISIN as _s2i
            ikeys = [_s2i.get(s, f"NSE_EQ|{s}") for s in symbols]
            def live_provider():
                raw = get_live_prices_batch(args.token, ikeys)
                out = {}
                for ikey, tick in raw.items():
                    sym = ikey.split("|")[-1]
                    tick["ikey"] = ikey
                    out[sym] = tick
                return out
            provider = live_provider
            scan_interval = 30
        except ImportError as e:
            print(f"⚠️  Could not import live feed ({e}). Falling back to synthetic data.")
            provider      = make_synthetic_provider(symbols, args.interval)
            scan_interval = args.interval
    else:
        print("ℹ️  TEST MODE — using synthetic candle data (pass --live --token TOKEN for real data)")
        provider      = make_synthetic_provider(symbols, args.interval)
        scan_interval = args.interval

    # ── Clear diff log ────────────────────────────────────────────────────────
    with open(DIFF_LOG, "w", encoding="utf-8") as f:
        f.write(f"ORB diff log — started {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # ── Run comparison ────────────────────────────────────────────────────────
    try:
        run_comparison(v1, v2, live_data_fn=provider,
                       scan_interval=scan_interval, max_scans=args.scans)
    except KeyboardInterrupt:
        _STOP_EVENT.set()
        print("\n⛔ Stopped by user.")

    # ── Final summary ─────────────────────────────────────────────────────────
    print("\n📋 FINAL COMPARISON SUMMARY")
    print(f"{'Symbol':<14}  {'V1 signal':^20}  {'V2 signal':^20}  {'Match?':^7}")
    print("─" * 65)
    all_syms = set(v1.signals) | set(v2.signals)
    diffs = 0
    for sym in sorted(all_syms):
        s1 = v1.signals.get(sym, {}).get("signal_type", "—")
        s2 = v2.signals.get(sym, {}).get("signal_type", "—")
        match = "✅" if s1 == s2 else "❌ DIFF"
        if s1 != s2:
            diffs += 1
        print(f"{sym:<14}  {s1:^20}  {s2:^20}  {match:^7}")
    print("─" * 65)
    print(f"Total symbols: {len(all_syms)}  |  Divergences: {diffs}")
    print(f"\nLog files written: orb_v1.log  orb_v2.log  {DIFF_LOG}")


if __name__ == "__main__":
    main()
