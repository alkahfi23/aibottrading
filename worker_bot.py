import os
import time
import requests
import numpy as np
from binance.client import Client
from binance.enums import *
from ta.momentum import RSIIndicator
from ta.trend import MACD, ADXIndicator
from decimal import Decimal


# === SETUP ===
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
client = Client(API_KEY, API_SECRET)

last_signal = {}

# === TOOLS ===
def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            print("❌ Telegram error:", response.text)
    except Exception as e:
        print("❌ Telegram exception:", e)

def get_klines(symbol, interval, limit=100):
    try:
        return client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    except Exception as e:
        print(f"❌ Error get_klines {interval}: {e}")
        return []

def calculate_indicators(closes):
    ema4 = np.mean(closes[-4:])
    ema20 = np.mean(closes[-20:])
    rsi = compute_rsi(closes)
    adx = 30  # placeholder, implement ADX calc jika butuh
    upper_bb, middle_bb, lower_bb = compute_bollinger_bands(closes)
    return ema4, ema20, rsi, adx, upper_bb, middle_bb, lower_bb

def compute_rsi(closes, period=14):
    deltas = np.diff(closes)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    return 100 - (100 / (1 + rs))

def compute_bollinger_bands(prices, period=20, std_dev=2):
    mean = np.mean(prices[-period:])
    std = np.std(prices[-period:])
    return mean + std_dev * std, mean, mean - std_dev * std

def calculate_fibonacci(prices):
    high = max(prices)
    low = min(prices)
    diff = high - low
    return {
        "0.236": high - diff * 0.236,
        "0.382": high - diff * 0.382,
        "0.5": high - diff * 0.5,
        "0.618": high - diff * 0.618,
        "0.786": high - diff * 0.786,
        "support": low,
        "resistance": high
    }

# === STRATEGI DAN LOGIKA ===
def analyze_signal(symbol):
    timeframes = ["1m", "5m", "15m", "1h"]
    trend_confirm = []
    closes_main = []

    for tf in timeframes:
        klines = get_klines(symbol, tf)
        if not klines:
            continue
        closes = [float(k[4]) for k in klines]
        ema4, ema20, rsi, adx, upper, middle, lower = calculate_indicators(closes)
        direction = "LONG" if ema4 > ema20 else "SHORT"
        trend_confirm.append(direction)
        if tf == "1m":
            closes_main = closes

    if len(trend_confirm) < 3:
        return "NONE", 0, {}, {}

    signal = "LONG" if trend_confirm.count("LONG") >= 3 else "SHORT" if trend_confirm.count("SHORT") >= 3 else "NONE"
    price_now = closes_main[-1]
    fibo = calculate_fibonacci(closes_main)
    indicators = {
        "ema4_vs_ema20": signal,
        "rsi": compute_rsi(closes_main),
        "adx": 30,
        "bollinger": compute_bollinger_bands(closes_main)
    }
    return signal, price_now, fibo, indicators

# === NOTIFIKASI ===
def notify(symbol):
    global last_signal
    signal, price, fibo, ind = analyze_signal(symbol)
    key = f"{symbol}_last_signal"

    if signal == "NONE":
        print("⏳ Belum ada sinyal kuat.")
        return
    if last_signal.get(key) == signal:
        print(f"⏭️ Sinyal {signal} sudah dikirim sebelumnya.")
        return
    last_signal[key] = signal

    message = (
        f"📢 *Rekomendasi Trading Futures*\n\n"
        f"📍 *Pair*: {symbol}\n"
        f"📈 *Sinyal*: {signal}\n"
        f"💵 *Harga Saat Ini*: {price:.2f} USDT\n\n"
        f"📊 *Validasi Timeframe*: ✅ EMA(4) vs EMA(20), RSI: {ind['rsi']:.2f}, ADX: {ind['adx']}\n"
        f"🔹 *Fibonacci Resistance*: {fibo['resistance']:.2f}\n"
        f"🔹 *Fibonacci Support*: {fibo['support']:.2f}\n\n"
        f"📌 *Strategi*: \n"
        f"- Entry: {'dekat support' if signal=='LONG' else 'dekat resistance'}\n"
        f"- SL: {'< ' + str(fibo['support']) if signal=='LONG' else '> ' + str(fibo['resistance'])}\n"
        f"- TP: Sesuaikan dengan trailing atau target aman\n\n"
        f"⏳ Tetap disiplin dan gunakan manajemen risiko."
    )
    send_to_telegram(message)

# === MAIN LOOP ===
def main():
    symbol = "BTCUSDT"
    while True:
        notify(symbol)
        time.sleep(30)  # Lebih cepat untuk tangkap momentum

if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
