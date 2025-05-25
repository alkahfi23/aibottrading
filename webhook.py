import os
import requests
import numpy as np
import time
from flask import Flask, request
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

def get_active_futures_pairs():
    try:
        info = client.futures_exchange_info()
        return sorted([s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL"])
    except Exception as e:
        print("❌ ERROR get_active_futures_pairs:", e)
        return []

def get_top_volume_pairs(limit=10):
    try:
        tickers = client.futures_ticker()
        sorted_pairs = sorted(tickers, key=lambda x: float(x["quoteVolume"]), reverse=True)
        return [(t["symbol"], float(t["quoteVolume"])) for t in sorted_pairs[:limit]]
    except:
        return []

def get_support_resistance_pairs(limit=30):
    pairs = get_active_futures_pairs()
    near_support, near_resistance = [], []
    for symbol in pairs[:limit]:
        try:
            klines = get_klines(symbol, interval="1h")
            if not klines:
                continue
            closes = [float(k[4]) for k in klines]
            price_now = closes[-1]
            levels = fibonacci_levels(closes)
            support = levels["0.618"]
            resistance = levels["0.236"]
            tolerance = 0.003  # 0.3%

            if abs(price_now - support) / support <= tolerance:
                near_support.append((symbol, price_now, support))
            if abs(price_now - resistance) / resistance <= tolerance:
                near_resistance.append((symbol, price_now, resistance))
        except:
            continue
    return near_support, near_resistance

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

    if trend["LONG"] >= 2:
        signal = "LONG"
    elif trend["SHORT"] >= 2:
        signal = "SHORT"
    else:
        signal = "NONE"

    confidence = max(trend["LONG"], trend["SHORT"]) * 25  # 0–100 scale
    recommendation = "Entry Saat Ini" if signal != "NONE" else "Tunggu Konfirmasi"

    return signal, price_now, levels, confidence, recommendation

# --- Webhook Endpoint ---
@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" not in data:
        return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "").strip().upper()

    if text == "PAIRS":
        pairs = get_active_futures_pairs()
        if not pairs:
            send_telegram(chat_id, "⚠️ Gagal mengambil daftar pair dari Binance.")
        else:
            message = "✅ Daftar Pair Binance Futures Aktif:\n"
            message += ", ".join(pairs[:50]) + "..."
            send_telegram(chat_id, message)
        return "ok", 200

    if text == "PAIRSVOL":
        top_vols = get_top_volume_pairs()
        if not top_vols:
            send_telegram(chat_id, "⚠️ Gagal mengambil data volume.")
        else:
            msg = "🔥 Top 10 Volume Pair Binance Futures:\n"
            for s, v in top_vols:
                msg += f"• {s} - {v:.2f}\n"
            send_telegram(chat_id, msg)
        return "ok", 200

    if text == "PAIRSUP":
        near_support, _ = get_support_resistance_pairs()
        if not near_support:
            send_telegram(chat_id, "Tidak ada pair yang dekat dengan support saat ini.")
        else:
            msg = "🟢 Pair Dekat Support (±0.3% dari Fib 0.618):\n"
            for s, p, lvl in near_support:
                msg += f"• {s}: {p:.2f} (Support: {lvl:.2f})\n"
            send_telegram(chat_id, msg)
        return "ok", 200

    if text == "PAIREST":
        _, near_resistance = get_support_resistance_pairs()
        if not near_resistance:
            send_telegram(chat_id, "Tidak ada pair yang dekat dengan resistance saat ini.")
        else:
            msg = "🔴 Pair Dekat Resistance (±0.3% dari Fib 0.236):\n"
            for s, p, lvl in near_resistance:
                msg += f"• {s}: {p:.2f} (Resistance: {lvl:.2f})\n"
            send_telegram(chat_id, msg)
        return "ok", 200

    if not text.isalnum() or len(text) < 6:
        return "ok", 200

    now = time.time()
    if now - last_request_time[chat_id] < RATE_LIMIT_SECONDS:
        send_telegram(chat_id, "⏳ Tunggu sebentar ya, coba lagi 1 menit lagi.")
        return "ok", 200
    last_request_time[chat_id] = now

    def handle_signal():
        symbol = text
        if not is_valid_futures_symbol(symbol):
            send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan di Binance Futures.")
            return
        try:
            signal, price, fibo, confidence, recommendation = analyze_signal(symbol)
            if signal == "NONE":
                send_telegram(chat_id, f"⚠️ Belum ada sinyal valid untuk {symbol} saat ini.")
            else:
                fibo_str = "\n".join([f"🔹 {k}: {v:.2f}" for k, v in fibo.items()])
                message = (
                    f"📊 Rekomendasi Trading Futures\n"
                    f"📍 Pair: {symbol}\n"
                    f"🧭 Sinyal: {signal}\n"
                    f"💰 Harga Sekarang: {price:.2f}\n"
                    f"✅ Rekomendasi: {recommendation}\n"
                    f"📊 Skor Kepercayaan: {confidence}%\n"
                    f"📐 Fibonacci Levels:\n{fibo_str}\n"
                    f"🟢 Support (0.618): {fibo['0.618']:.2f}\n"
                    f"🔴 Resistance (0.236): {fibo['0.236']:.2f}"
                )
                send_telegram(chat_id, message)
        except Exception as e:
            print("❌ ERROR:", e)
            send_telegram(chat_id, "❌ Terjadi kesalahan saat memproses sinyal.")

    Thread(target=handle_signal).start()
    return "ok", 200

# --- Run App ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
