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
    if len(prices) < window:
        return np.mean(prices)
    return np.mean(prices[-window:])

def calculate_bollinger_bands(prices, window=20, num_std_dev=2):
    if len(prices) < window:
        return None, None, None
    prices = np.array(prices[-window:])
    sma = np.mean(prices)
    std = np.std(prices)
    upper_band = sma + num_std_dev * std
    lower_band = sma - num_std_dev * std
    return lower_band, sma, upper_band

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

def get_ema_direction(symbol, interval="1h", limit=20):
    klines = get_klines(symbol, interval, limit)
    if not klines:
        return "NONE"
    closes = [float(k[4]) for k in klines]
    ema4 = calculate_ema(closes, 4)
    ema20 = calculate_ema(closes, 20)
    return "LONG" if ema4 > ema20 else "SHORT"

# === ANALISIS SINYAL ===
def analyze_signal(symbol):
    timeframes = {"1m": 20, "5m": 20, "15m": 20}
    trend_confirm = {}
    last_close = 0
    fibo = {}
    bb_signal = "NONE"

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
            bb_lower, bb_mid, bb_upper = calculate_bollinger_bands(closes)
            if bb_lower and last_close < bb_lower:
                bb_signal = "LONG"
            elif bb_upper and last_close > bb_upper:
                bb_signal = "SHORT"

    # Konfirmasi 1 jam
    confirm_1h = get_ema_direction(symbol, interval="1h")

    directions = list(trend_confirm.values())
    if directions.count("LONG") >= 2 and bb_signal == "LONG" and confirm_1h == "LONG":
        return "LONG", last_close, fibo, bb_signal, confirm_1h
    elif directions.count("SHORT") >= 2 and bb_signal == "SHORT" and confirm_1h == "SHORT":
        return "SHORT", last_close, fibo, bb_signal, confirm_1h
    else:
        return "NONE", last_close, fibo, bb_signal, confirm_1h

# === NOTIFIKASI ===
def notify(symbol):
    global last_signal
    signal, price, fibo, bb_sig, conf_1h = analyze_signal(symbol)
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
        f"💵 Harga Saat Ini: {price:.2f}\n"
        f"📊 Bollinger Band Sinyal: {bb_sig}\n"
        f"🕐 Konfirmasi 1H: {conf_1h}\n"
        f"📐 Fibonacci Support/Resistance:\n{fibo_str}"
    )
    send_to_telegram(message)

# === LOOP UTAMA ===
def main():
    symbol = "BTCUSDT"
    while True:
        notify(symbol)
        time.sleep(60)

if __name__ == "__main__":
    main()

