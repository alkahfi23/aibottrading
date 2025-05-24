import os
import time
import requests
from binance.client import Client
from binance.enums import *
import numpy as np

# === SETUP ===
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(API_KEY, API_SECRET)
last_signal = {}

# === TOOLS ===
def send_to_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("✅ Telegram terkirim.")
        else:
            print(f"❌ Gagal Telegram: {response.text}")
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

def get_klines(symbol, interval, limit=100):
    try:
        return client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    except Exception as e:
        print(f"❌ Error ambil kline {interval}: {e}")
        return []

def calculate_ema(prices, window):
    if len(prices) < window:
        return np.mean(prices)
    return np.mean(prices[-window:])

def calculate_fibonacci_support_resistance(prices):
    high = max(prices)
    low = min(prices)
    diff = high - low
    levels = {
        "0.236": high - diff * 0.236,
        "0.382": high - diff * 0.382,
        "0.5": high - diff * 0.5,
        "0.618": high - diff * 0.618,
        "0.786": high - diff * 0.786
    }
    return levels

# === ANALISIS SINYAL ===
def analyze_signal(symbol):
    try:
        timeframes = {"1m": 20, "5m": 20, "15m": 20}
        trend_confirm = {}
        last_close = 0
        fibo = {}

        for tf, limit in timeframes.items():
            klines = get_klines(symbol, tf, limit)
            if not klines:
                continue
            closes = [float(k[4]) for k in klines]
            ema4 = calculate_ema(closes, 4)
            ema20 = calculate_ema(closes, 20)

            trend_confirm[tf] = "LONG" if ema4 > ema20 else "SHORT"
            if tf == "1m":
                last_close = closes[-1]
                fibo = calculate_fibonacci_support_resistance(closes)

        # Mayoritas konfirmasi arah
        directions = list(trend_confirm.values())
        if directions.count("LONG") >= 2:
            return "LONG", last_close, fibo
        elif directions.count("SHORT") >= 2:
            return "SHORT", last_close, fibo
        else:
            return "NONE", last_close, fibo

    except Exception as e:
        print(f"❌ Error analyze_signal: {e}")
        return "NONE", 0.0, {}

# === NOTIFIKASI ===
def notify(symbol):
    global last_signal
    signal, price, fibo = analyze_signal(symbol)
    if signal == "NONE":
        print("⏸️ Tidak ada sinyal.")
        return

    key = f"{symbol}_signal"
    if last_signal.get(key) == signal:
        print("🔁 Sinyal sama, tidak dikirim ulang.")
        return

    last_signal[key] = signal
    fibo_str = "\n".join([f"🔹 {k}: {v:.2f}" for k, v in fibo.items()])
    message = (
        f"📢 Sinyal Trading Futures\n"
        f"📍 Symbol: {symbol}\n"
        f"🧭 Sinyal: {signal}\n"
        f"💵 Harga Saat Ini: {price}\n"
        f"📐 Fibonacci Support/Resistance:\n{fibo_str}"
    )
    send_to_telegram(message)

# === LOOP UTAMA ===
def main():
    symbol = "BTCUSDT"
    while True:
        notify(symbol)
        time.sleep(60)  # tiap 1 menit

if __name__ == "__main__":
    main()
