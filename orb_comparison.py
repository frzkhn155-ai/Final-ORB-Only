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