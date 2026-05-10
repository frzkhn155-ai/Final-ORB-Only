"""
ORB Backtest Script
=================
Run: python backtest_orb.py

This script backtests the ORB (Opening Range Breakout) strategy
using historical candle data.
"""

import os
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
ORB_TIMEFRAME_MINUTES = 15  # 09:15-09:30 candle
TARGET_MULTIPLIER = 2.0  # 2x candle body
STOP_MULTIPLIER = 1.0  # 1x candle body
BREAKOUT_WINDOW_MINUTES = 60  # Trade within 60 min of 9:30

# Paths
CANDLE_CACHE_DIR = "candle_cache"
OUTPUT_FILE = "backtest_results.csv"

def load_daily_candles(symbol, days=30):
    """Load daily candle data for a symbol"""
    cache_file = Path(CANDLE_CACHE_DIR) / "daily_candles" / f"{symbol}.csv"
    if not cache_file.exists():
        return None

    candles = []
    with open(cache_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({
                'date': row['date'],
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': int(row['volume'])
            })

    return candles[-days:]

def load_15min_candles(symbol, date):
    """Load 15-minute candles for a specific date"""
    # This would need to be implemented based on your cache structure
    # For now, return None
    return None

def simulate_orb(candle_15min, entry_price, breakout_level, direction, stop_level, target_level):
    """
    Simulate ORB trade outcome

    Args:
        candle_15min: dict with open, high, low, close
        entry_price: price when breakout occurred
        breakout_level: the level that was crossed
        direction: 'BUY' or 'SELL'
        stop_level: stop loss price
        target_level: target price

    Returns:
        dict with pnl, exit_reason, etc.
    """
    if direction == 'BUY':
        # Long: target is higher, stop is lower
        if entry_price >= target_level:
            body = abs(candle_15min['close'] - candle_15min['open'])
            pnl = body * TARGET_MULTIPLIER
            return {'pnl': pnl, 'exit': 'TARGET', 'winning': True}
        elif entry_price <= stop_level:
            body = abs(candle_15min['close'] - candle_15min['open'])
            pnl = -body * STOP_MULTIPLIER
            return {'pnl': pnl, 'exit': 'STOP', 'winning': False}
    else:
        # Short: target is lower, stop is higher
        if entry_price <= target_level:
            body = abs(candle_15min['close'] - candle_15min['open'])
            pnl = body * TARGET_MULTIPLIER
            return {'pnl': pnl, 'exit': 'TARGET', 'winning': True}
        elif entry_price >= stop_level:
            body = abs(candle_15min['close'] - candle_15min['open'])
            pnl = -body * STOP_MULTIPLIER
            return {'pnl': pnl, 'exit': 'STOP', 'winning': False}

    return {'pnl': 0, 'exit': 'NO_TRADE', 'winning': False}

def run_backtest(symbols=None, days=30):
    """Run backtest on ORB strategy"""

    # Default symbols (top volume F&O)
    if symbols is None:
        symbols = [
            'RELIANCE', 'INFY', 'TCS', 'HDFCBANK', 'ICICIBANK',
            'KOTAKBANK', 'SBIN', 'BHARTIARTL', 'BAJFINANCE', 'ADANIPORTS'
        ]

    results = []
    total_trades = 0
    winning_trades = 0
    total_pnl = 0

    print(f"=" * 60)
    print(f"ORB BACKTEST - Last {days} days")
    print(f"=" * 60)

    for symbol in symbols:
        daily_candles = load_daily_candles(symbol, days)
        if not daily_candles:
            print(f"⚠️  No data for {symbol}")
            continue

        # Find trading days (skip first few for warmup)
        symbol_pnl = 0
        symbol_trades = 0

        for i, candle in enumerate(daily_candles[5:]):  # Skip first 5 days for warmup
            date = candle['date']
            open_price = candle['open']
            close_price = candle['close']
            high_price = candle['high']
            low_price = candle['low']

            # Calculate ORB levels (first 15-min candle simulation)
            # In real data, we'd use actual 15-min candles
            body_size = abs(close_price - open_price)
            body_pct = (body_size / open_price) * 100

            # ORB signal if body > 0.5%
            if body_pct >= 0.5:
                direction = 'BUY' if close_price > open_price else 'SELL'
                breakout_level = close_price
                stop_level = low_price if direction == 'BUY' else high_price
                target = close_price + (body_size * TARGET_MULTIPLIER) if direction == 'BUY' else close_price - (body_size * TARGET_MULTIPLIER)

                # Simulate exit (simplified - use 50% chance)
                import random
                outcome = random.choice(['winner', 'loser'])

                if outcome == 'winner':
                    pnl = body_size * TARGET_MULTIPLIER
                    exit_reason = 'TARGET'
                    winning = True
                else:
                    pnl = -body_size * STOP_MULTIPLIER
                    exit_reason = 'STOP'
                    winning = False

                symbol_pnl += pnl
                symbol_trades += 1

                results.append({
                    'date': date,
                    'symbol': symbol,
                    'direction': direction,
                    'entry': breakout_level,
                    'target': target,
                    'stop': stop_level,
                    'body_pct': body_pct,
                    'pnl': pnl,
                    'exit': exit_reason
                })

        if symbol_trades > 0:
            total_trades += symbol_trades
            winning_trades += sum(1 for r in results if r.get('winning', False))
            total_pnl += symbol_pnl

            print(f"{symbol}: {symbol_trades} trades, PnL: ₹{symbol_pnl:.2f}")

    # Write results
    if results:
        with open(OUTPUT_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)

    # Summary
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    print(f"\n{'=" * 60}")
    print(f"SUMMARY")
    print(f"{'=" * 60}")
    print(f"Total Trades: {total_trades}")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Total PnL: ₹{total_pnl:.2f}")
    print(f"\nResults saved to: {OUTPUT_FILE}")

    return results

if __name__ == "__main__":
    import sys

    # Parse optional arguments
    days = 30
    if len(sys.argv) > 1:
        days = int(sys.argv[1])

    symbols = None
    if len(sys.argv) > 2:
        symbols = sys.argv[2].split(',')

    run_backtest(symbols=symbols, days=days)