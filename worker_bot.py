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


def calculate_bollinger_bands(prices, window=20):
    closes = np.array(prices[-window:])
    sma = np.mean(closes)
    std = np.std(closes)
    upper = sma + 2 * std
    lower = sma - 2 * std
    return upper, sma, lower


def calculate_fibonacci_levels(prices):
    high = max(prices)
    low = min(prices)
    diff = high - low
    levels = {
        "0.236": high - diff * 0.236,
        "0.382": high - diff * 0.382,
        "0.5": high - diff * 0.5,
        "0.618": high - diff * 0.618,
        "0.786": high - diff * 0.786,
    }
    return levels


def volume_spike(volumes):
    avg = np.mean(volumes[:-1])
    return volumes[-1] > avg * 1.5


def detect_signal(symbol):
    try:
        timeframes = ["1m", "5m", "15m", "1h"]
        trend_confirm = []

        for tf in timeframes:
            klines = get_klines(symbol, tf, 100)
            if not klines:
                continue
            closes = [float(k[4]) for k in klines]
            volumes = [float(k[5]) for k in klines]
            ema4 = calculate_ema(closes, 4)
            ema20 = calculate_ema(closes, 20)
            upper, sma, lower = calculate_bollinger_bands(closes)
            dir_trend = "LONG" if ema4 > ema20 and closes[-1] > sma else "SHORT"
            valid_volume = volume_spike(volumes)

            if valid_volume:
                trend_confirm.append(dir_trend)

        signal = "NONE"
        if trend_confirm.count("LONG") >= 3:
            signal = "LONG"
        elif trend_confirm.count("SHORT") >= 3:
            signal = "SHORT"

        closes_final = [float(k[4]) for k in get_klines(symbol, "1m", 100)]
        price_now = closes_final[-1]
        fibo = calculate_fibonacci_levels(closes_final)

        return signal, price_now, fibo

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
        f"💵 Harga Sekarang: {price:.2f}\n"
        f"📐 Fibonacci Support/Resistance:\n{fibo_str}"
    )
    send_to_telegram(message)


# === LOOP UTAMA ===
def main():
    symbol = "BTCUSDT"
    while True:
        notify_signal(symbol)
        time.sleep(50)


if __name__ == "__main__":
    main()
