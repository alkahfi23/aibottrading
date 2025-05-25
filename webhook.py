import os
import requests
import numpy as np
import time
import matplotlib.pyplot as plt
import io
from flask import Flask, request, send_file
from binance.client import Client
from collections import defaultdict
from threading import Thread

app = Flask(__name__)

# ENV
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
last_request_time = defaultdict(float)
RATE_LIMIT_SECONDS = 60

# --- Tools ---
def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    requests.post(url, data=payload)

def send_telegram_photo(chat_id, image_bytes, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", image_bytes)}
    data = {"chat_id": chat_id, "caption": caption}
    requests.post(url, files=files, data=data)

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
    confidence = max(trend["LONG"], trend["SHORT"]) / 4
    return signal, price_now, levels, confidence

def get_active_futures_pairs():
    try:
        info = client.futures_exchange_info()
        return [s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL"]
    except:
        return []

def get_top_volume_pairs():
    try:
        tickers = client.futures_ticker()
        sorted_by_vol = sorted(tickers, key=lambda x: float(x["quoteVolume"]), reverse=True)
        return [x["symbol"] for x in sorted_by_vol[:10]]
    except:
        return []

def detect_support_resistance():
    support = []
    resistance = []
    pairs = get_active_futures_pairs()
    for symbol in pairs:
        klines = get_klines(symbol, "1h")
        if not klines:
            continue
        closes = [float(k[4]) for k in klines]
        fibo = fibonacci_levels(closes)
        price = closes[-1]

        if abs(price - fibo["0.618"]) / price < 0.003:
            support.append((symbol, price, fibo["0.618"]))
        if abs(price - fibo["0.236"]) / price < 0.003:
            resistance.append((symbol, price, fibo["0.236"]))
    return support, resistance

def plot_fibonacci_chart(symbol):
    klines = get_klines(symbol, "1h", 100)
    closes = [float(k[4]) for k in klines]
    timestamps = [k[0] for k in klines]
    fibo = fibonacci_levels(closes)

    plt.figure(figsize=(10, 5))
    plt.plot(closes, label="Close Price", color="blue")
    for level, price in fibo.items():
        plt.axhline(y=price, linestyle="--", label=f"Fib {level} = {price:.2f}")
    plt.title(f"{symbol} - Fibonacci Support/Resistance")
    plt.legend()
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()
    return buf

# --- Webhook ---
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" not in data:
        return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "").strip().upper()

    # PAIRS command
    if text == "PAIRS":
        pairs = get_active_futures_pairs()
        msg = "✅ Pair Binance Futures:\n" + ", ".join(pairs[:50]) + "..."
        send_telegram(chat_id, msg)
        return "ok", 200

    # PAIRSVOL command
    if text == "PAIRSVOL":
        pairs = get_top_volume_pairs()
        if not pairs:
            send_telegram(chat_id, "⚠️ Gagal mengambil data volume.")
        else:
            send_telegram(chat_id, "🔥 Top 10 Pair Berdasarkan Volume:\n" + "\n".join(pairs))
        return "ok", 200

    # PAIRSUP / PAIREST
    if text == "PAIRSUP" or text == "PAIREST":
        support, resistance = detect_support_resistance()
        if text == "PAIRSUP":
            msg = "🟢 Pair Dekat Support (±0.3% dari Fib 0.618):\n"
            msg += "\n".join([f"• {s[0]}: {s[1]:.2f} (Support: {s[2]:.2f})" for s in support]) or "Tidak ada."
        else:
            msg = "🔴 Pair Dekat Resistance (±0.3% dari Fib 0.236):\n"
            msg += "\n".join([f"• {s[0]}: {s[1]:.2f} (Resistance: {s[2]:.2f})" for s in resistance]) or "Tidak ada."
        send_telegram(chat_id, msg)
        return "ok", 200

    # CHART <symbol>
    if text.startswith("CHART "):
        symbol = text.split(" ")[1]
        if not is_valid_futures_symbol(symbol):
            send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan.")
        else:
            img = plot_fibonacci_chart(symbol)
            send_telegram_photo(chat_id, img, caption=f"📊 Chart {symbol} + Fibonacci")
        return "ok", 200

    # Validasi simbol
    if not text.isalnum() or len(text) < 6:
        return "ok", 200

    # Rate limit
    now = time.time()
    if now - last_request_time[chat_id] < RATE_LIMIT_SECONDS:
        send_telegram(chat_id, "⏳ Tunggu sebentar ya, coba lagi 1 menit lagi.")
        return "ok", 200
    last_request_time[chat_id] = now

    # Proses sinyal
    def handle_signal():
        symbol = text
        if not is_valid_futures_symbol(symbol):
            send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan.")
            return
        try:
            signal, price, fibo, confidence = analyze_signal(symbol)
            if signal == "NONE":
                send_telegram(chat_id, f"⚠️ Belum ada sinyal valid untuk {symbol}.")
            else:
                fibo_str = "\n".join([f"🔹 {k}: {v:.2f}" for k, v in fibo.items()])
                msg = (
                    f"📊 Sinyal Trading\n"
                    f"📍 Pair: {symbol}\n"
                    f"🧭 Sinyal: {signal}\n"
                    f"💰 Harga Sekarang: {price:.2f}\n"
                    f"📈 Kepercayaan: {confidence * 100:.1f}%\n"
                    f"📐 Fibonacci:\n{fibo_str}"
                )
                send_telegram(chat_id, msg)
        except Exception as e:
            print("❌ ERROR:", e)
            send_telegram(chat_id, "❌ Terjadi kesalahan saat memproses sinyal.")
    Thread(target=handle_signal).start()
    return "ok", 200

# --- Run ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
