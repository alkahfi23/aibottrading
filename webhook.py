import os
import requests
import numpy as np
import time
from flask import Flask, request
from binance.client import Client
from collections import defaultdict
from threading import Thread

app = Flask(__name__)

# === ENV ===
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = os.getenv("PORT")

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
last_request_time = defaultdict(float)
RATE_LIMIT_SECONDS = 60

# === TOOLS ===
def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    r = requests.post(url, data=payload)
    print(f"[Telegram] {r.status_code} | {r.text}")

def get_klines(symbol, interval="1m", limit=100):
    try:
        return client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    except:
        return []

def ema(prices, period):
    return np.mean(prices[-period:])

def bollinger_bands(prices, period=20, std_dev=2):
    ma = np.mean(prices[-period:])
    std = np.std(prices[-period:])
    return ma + std_dev * std, ma - std_dev * std

def fibonacci_levels(prices):
    high, low = max(prices), min(prices)
    diff = high - low
    return {
        "0.236": high - diff * 0.236,
        "0.382": high - diff * 0.382,
        "0.5": high - diff * 0.5,
        "0.618": high - diff * 0.618,
    }

def is_valid_futures_symbol(symbol):
    try:
        info = client.futures_exchange_info()
        symbols = [s["symbol"] for s in info["symbols"]]
        return symbol.upper() in symbols
    except:
        return False

def analyze_signal(symbol):
    trend = {"LONG": 0, "SHORT": 0}
    levels = {}
    price_now = 0

    for tf in ["1m", "5m", "15m", "1h"]:
        klines = get_klines(symbol, tf)
        if not klines:
            continue

        closes = [float(k[4]) for k in klines]
        ema4 = ema(closes, 4)
        ema20 = ema(closes, 20)
        upper, lower = bollinger_bands(closes)
        price_now = closes[-1]

        if ema4 > ema20 and price_now > upper:
            trend["LONG"] += 1
        elif ema4 < ema20 and price_now < lower:
            trend["SHORT"] += 1

        if tf == "1h":
            levels = fibonacci_levels(closes)

    signal = "LONG" if trend["LONG"] >= 2 else "SHORT" if trend["SHORT"] >= 2 else "NONE"
    return signal, price_now, levels

# === WEBHOOK ===
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" not in data:
        return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "").strip().upper()

    # Batasi input agar valid simbol
    if not text.isalnum() or len(text) < 6:
        return "ok", 200

    now = time.time()
    if now - last_request_time[chat_id] < RATE_LIMIT_SECONDS:
        send_telegram(chat_id, "⏳ Tunggu sebentar ya, grup ini baru saja kirim permintaan. Coba lagi 1 menit lagi.")
        return "ok", 200

    last_request_time[chat_id] = now

    # Proses sinyal di thread baru agar respons cepat ke Telegram
    def handle_signal():
        symbol = text
        if not is_valid_futures_symbol(symbol):
            send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan di Binance Futures.")
            return

        try:
            signal, price, fibo = analyze_signal(symbol)
            if signal == "NONE":
                send_telegram(chat_id, f"⚠️ Belum ada sinyal valid untuk {symbol} saat ini.")
            else:
                fibo_str = "\n".join([f"🔹 {k}: {v:.2f}" for k, v in fibo.items()])
                message = (
                    f"📊 Rekomendasi Trading Futures\n"
                    f"📍 Pair: {symbol}\n"
                    f"🧭 Sinyal: {signal}\n"
                    f"💰 Harga Sekarang: {price:.2f}\n"
                    f"📐 Support & Resistance (Fibonacci):\n{fibo_str}"
                )
                send_telegram(chat_id, message)
        except Exception as e:
            print("❌ ERROR:", e)
            send_telegram(chat_id, "❌ Terjadi kesalahan saat memproses sinyal.")

    Thread(target=handle_signal).start()
    return "ok", 200

# === RUN APP ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # disarankan port 5000
    app.run(host="0.0.0.0", port=port)
