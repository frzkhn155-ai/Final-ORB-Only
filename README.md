# Upstox Auto-Trading Bot — ORB Only

Real-time F&O options trading bot for NSE using Upstox API.
**This version runs ONLY the Opening Range Breakout (ORB) strategy.**

---

## Strategy

- **ORB** — Opening Range Breakout at 09:20 using 15-min candles

### ORB Configuration (already set in bot)

| Parameter | Value |
|-----------|-------|
| ORB_TIMEFRAME_MINUTES | 15 (9:15-9:30) |
| ORB_BREAKOUT_WINDOW_MINUTES | 60 (trade until 10:30) |
| ORB_TARGET_MULTIPLIER | 2.0x candle body |
| ORB_STOP_MULTIPLIER | 1.0x candle body |
| ORB_MIN_CANDLE_BODY_PERCENT | 0.5% |
| ORB_VOLUME_CONFIRMATION | 1.5x average volume |
| Klinger Gate | Enabled |
| RSI Gate | Enabled |

---

## Files

| File | Purpose |
|------|---------|
| `Both4withcache10_headless.py` | Main bot — ORB strategy only |
| `ai_assistant.py` | AI assistant (optional) |
| `orb_comparison.py` | Dual-engine ORB comparison harness (V1 IST vs V2 local clock) |
| `requirements.txt` | Python dependencies |

---

## ORB Comparison Harness (`orb_comparison.py`)

Runs two ORB implementations side-by-side to compare signal and breakout output.

- **V1 (IST-aware)** — uses `pytz` / `now_ist()`
- **V2 (local clock)** — uses `datetime.now()`

### Usage

```bash
# Test mode (synthetic data, no market connection needed)
python orb_comparison.py

# Live mode (requires Upstox token)
python orb_comparison.py --token YOUR_UPSTOX_TOKEN --live
```

Output is written to `orb_v1.log`, `orb_v2.log`, and `orb_diff.log` (divergences only).

---

## Setup

### 1. Install Python packages

```bash
pip install -r requirements.txt
```

### 2. Chrome + ChromeDriver

Chrome must be installed. webdriver-manager handles ChromeDriver automatically.

### 3. Configure credentials

Edit `Both4withcache10_headless.py` lines 43-60:

```python
EMAIL           = "your_email@gmail.com"
EMAIL_PASSWORD  = "your_gmail_app_password"
MOBILE_NUMBER   = "9999999999"
PASSCODE       = "your_upstox_passcode"

UPSTOX_API_KEY     = "your_client_id"
UPSTOX_API_SECRET = "your_client_secret"
```

### 4. (Optional) Set Upstox token

```python
HARDCODED_TOKEN = "eyJ..."
USE_HARDCODED_TOKEN = True
```

---

## Running

```bash
python Both4withcache10_headless.py
```

---

## Key Flags

| Flag | Default | Description |
|------|---------|--------------|
| TEST_MODE | True | Run anytime (disable for production) |
| ENABLE_AUTO_TRADING | True | Place real orders |
| DEBUG_MODE | False | Verbose output (set True for debugging) |

---

## Disabled Strategies

All other strategies are disabled:
- GAP_TRADING = False
- BOX_TRADING = False
- RANGE_TRADING = False
- FAST_TRADING = False
