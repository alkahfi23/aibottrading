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
            print(f"❌ Telegram error: {response.text}")
    except Exception as e:
        print(f"❌ Telegram exception: {e}")

def get_klines(symbol, interval, limit=100):
    try:
        return client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    except Exception as e:
        print(f"❌ Kline error {interval}: {e}")
        return []

def calculate_indicators(closes):
    closes_np = np.array(closes)
    rsi = RSIIndicator(close=closes_np).rsi().iloc[-1]
    macd = MACD(close=closes_np)
    adx = ADXIndicator(high=closes_np, low=closes_np, close=closes_np).adx().iloc[-1]
    return {
        "rsi": rsi,
        "macd": macd.macd().iloc[-1],
        "macd_signal": macd.macd_signal().iloc[-1],
        "adx": adx,
    }

def calculate_fibonacci(prices):
    high, low = max(prices), min(prices)
    diff = high - low
    levels = {
        "0.236": high - diff * 0.236,
        "0.382": high - diff * 0.382,
        "0.5": high - diff * 0.5,
        "0.618": high - diff * 0.618,
        "0.786": high - diff * 0.786,
    }
    return levels

def analyze_signal(symbol):
    timeframes = ["1m", "5m", "15m"]
    confirmations = []
    for tf in timeframes:
        klines = get_klines(symbol, tf, 50)
        if not klines:
            continue
        closes = [float(k[4]) for k in klines]
        ema4 = np.mean(closes[-4:])
        ema20 = np.mean(closes[-20:])
        trend = "LONG" if ema4 > ema20 else "SHORT"

        indicators = calculate_indicators(closes)
        rsi_valid = indicators["rsi"] > 50 if trend == "LONG" else indicators["rsi"] < 50
        macd_valid = indicators["macd"] > indicators["macd_signal"] if trend == "LONG" else indicators["macd"] < indicators["macd_signal"]
        adx_valid = indicators["adx"] > 20

        if rsi_valid and macd_valid and adx_valid:
            confirmations.append(trend)

    final = "LONG" if confirmations.count("LONG") >= 2 else "SHORT" if confirmations.count("SHORT") >= 2 else "NONE"
    return final, closes[-1], calculate_fibonacci(closes)

def notify(symbol):
    global last_signal
    signal, price, fibo = analyze_signal(symbol)
    if signal == "NONE":
        print("⚠️ Tidak ada sinyal valid.")
        return
    if last_signal.get(symbol) == signal:
        print("⏭️ Sinyal sama, tidak kirim ulang.")
        return
    last_signal[symbol] = signal

    fibo_msg = "\n".join([f"🔹 {k}: {v:.2f}" for k, v in fibo.items()])
    message = (
        f"📢 Sinyal Trading Futures\n"
        f"📍 Symbol: {symbol}\n"
        f"🧭 Sinyal: {signal}\n"
        f"💵 Harga: {price}\n"
        f"📐 Fibonacci Support/Resistance:\n{fibo_msg}"
    )
    send_to_telegram(message)

def main():
    symbol = "BTCUSDT"
    while True:
        notify(symbol)
        time.sleep(60)

if __name__ == "__main__":
    main()
