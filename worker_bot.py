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
last_signal = {}  # Hindari duplikat notifikasi

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


def detect_signal(symbol):
    try:
        timeframes = {"1m": 20, "5m": 20, "15m": 20}
        trend_confirm = {}
        closes = []

        for tf, limit in timeframes.items():
            klines = get_klines(symbol, tf, limit)
            if not klines:
                continue
            tf_closes = [float(k[4]) for k in klines]
            ema4 = calculate_ema(tf_closes, 4)
            ema20 = calculate_ema(tf_closes, 20)
            trend_confirm[tf] = "LONG" if ema4 > ema20 else "SHORT"
            if tf == "1m":
                closes = tf_closes  # gunakan close terakhir dari 1m

        if list(trend_confirm.values()).count("LONG") >= 2:
            return "LONG", closes[-1], calculate_fibonacci_support_resistance(closes)
        elif list(trend_confirm.values()).count("SHORT") >= 2:
            return "SHORT", closes[-1], calculate_fibonacci_support_resistance(closes)
        else:
            return "NONE", closes[-1] if closes else 0.0, {}

    except Exception as e:
        print(f"❌ Error detect_signal: {e}")
        return "NONE", 0.0, {}


def notify_signal(symbol):
    global last_signal
    signal, price, fibo = detect_signal(symbol)
    if signal == "NONE":
        print("⚠️ Tidak ada sinyal valid saat ini.")
        return

    key = f"{symbol}_signal"
    if last_signal.get(key) == signal:
        print(f"⏭️ Sinyal sama ({signal}), tidak dikirim ulang.")
        return

    last_signal[key] = signal
    fibo_str = "\n".join([f"🔹 {k}: {v:.2f}" for k, v in fibo.items()])
    message = (
        f"📢 Sinyal Trading Futures\n"
        f"📍 Symbol: {symbol}\n"
        f"🧭 Sinyal: {signal}\n"
        f"💵 Harga Saat Ini: {price:.2f}\n"
        f"📐 Fibonacci Levels:\n{fibo_str}"
    )
    send_to_telegram(message)


# === LOOP UTAMA ===
def main():
    symbol = "BTCUSDT"
    while True:
        notify_signal(symbol)
        time.sleep(60)  # Cek sinyal setiap 1 menit


if __name__ == "__main__":
    main()
