import os
import requests
import numpy as np
import time
from flask import Flask, request
from binance.client import Client
from collections import defaultdict
from threading import Thread

app = Flask(__name__)

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
last_request_time = defaultdict(float)
RATE_LIMIT_SECONDS = 60

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
    score = trend["LONG"] if signal == "LONG" else trend["SHORT"]
    return signal, price_now, levels, score

def get_active_futures_pairs():
    try:
        info = client.futures_exchange_info()
        symbols = [s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL"]
        return sorted(symbols)
    except:
        return []

def get_top_volume_pairs():
    try:
        tickers = client.futures_ticker()
        sorted_tickers = sorted(tickers, key=lambda x: float(x["quoteVolume"]), reverse=True)
        return [t["symbol"] for t in sorted_tickers[:10]]
    except:
        return []

def check_support_resistance():
    support_list = []
    resistance_list = []
    tolerance = 0.003  # 0.3%

    for symbol in get_active_futures_pairs():
        klines = get_klines(symbol, "1h")
        if not klines:
            continue
        closes = [float(k[4]) for k in klines]
        price_now = closes[-1]
        fibo = fibonacci_levels(closes)
        fib_618 = fibo["0.618"]
        fib_236 = fibo["0.236"]

        if abs(price_now - fib_618) / fib_618 < tolerance:
            support_list.append((symbol, price_now, fib_618))
        if abs(price_now - fib_236) / fib_236 < tolerance:
            resistance_list.append((symbol, price_now, fib_236))

    return support_list, resistance_list

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" not in data:
        return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "").strip().upper()

    now = time.time()
    if now - last_request_time[chat_id] < RATE_LIMIT_SECONDS:
        send_telegram(chat_id, "⏳ Tunggu sebentar ya, coba lagi 1 menit lagi.")
        return "ok", 200
    last_request_time[chat_id] = now

    if text == "PAIRS":
        pairs = get_active_futures_pairs()
        if not pairs:
            send_telegram(chat_id, "⚠️ Gagal mengambil daftar pair dari Binance.")
        else:
            msg = "✅ Daftar Pair Binance Futures Aktif (PERPETUAL):\n" + ", ".join(pairs[:50]) + "..."
            send_telegram(chat_id, msg)
        return "ok", 200

    if text == "PAIRSVOL":
        try:
            top_pairs = get_top_volume_pairs()
            msg = "🔥 10 Pair Volume Tertinggi:\n" + "\n".join(f"• {p}" for p in top_pairs)
            send_telegram(chat_id, msg)
        except:
            send_telegram(chat_id, "⚠️ Gagal mengambil data volume.")
        return "ok", 200

    if text == "PAIRSUP" or text == "PAIREST":
        support, resistance = check_support_resistance()
        if text == "PAIRSUP":
            msg = "🟢 Pair Dekat Support (±0.3% dari Fib 0.618):\n" + "\n".join(
                f"• {s}: {p:.2f} (Support: {f:.2f})" for s, p, f in support
            )
        else:
            msg = "🔴 Pair Dekat Resistance (±0.3% dari Fib 0.236):\n" + "\n".join(
                f"• {s}: {p:.2f} (Resistance: {f:.2f})" for s, p, f in resistance
            )
        send_telegram(chat_id, msg or "Tidak ada pair yang cocok saat ini.")
        return "ok", 200

    if text == "LONG" or text == "SHORT":
        pairs = get_active_futures_pairs()
        matched = []

        for symbol in pairs:
            signal, price, _, score = analyze_signal(symbol)
            if signal == text:
                matched.append(f"• {symbol} ({signal} / Score: {score})")

        if matched:
            msg = f"✅ Daftar Pair dengan Sinyal {text}:\n" + "\n".join(matched)
        else:
            msg = f"⚠️ Tidak ditemukan pair dengan sinyal {text} saat ini."
        send_telegram(chat_id, msg)
        return "ok", 200

    if not text.isalnum() or len(text) < 6:
        return "ok", 200

    def handle_signal():
        symbol = text
        if not is_valid_futures_symbol(symbol):
            send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan di Binance Futures.")
            return
        try:
            signal, price, fibo, score = analyze_signal(symbol)
            if signal == "NONE":
                send_telegram(chat_id, f"⚠️ Belum ada sinyal valid untuk {symbol} saat ini.")
            else:
                fibo_str = "\n".join([f"🔹 {k}: {v:.2f}" for k, v in fibo.items()])
                level_note = "🟢 Dekat Support!" if abs(price - fibo["0.618"]) / fibo["0.618"] < 0.003 else (
                             "🔴 Dekat Resistance!" if abs(price - fibo["0.236"]) / fibo["0.236"] < 0.003 else "")
                msg = (
                    f"📊 Rekomendasi Trading Futures\n"
                    f"📍 Pair: {symbol}\n"
                    f"🧭 Sinyal: {signal} (Skor: {score}/4)\n"
                    f"💰 Harga Sekarang: {price:.2f}\n"
                    f"📐 Fibonacci Levels:\n{fibo_str}\n"
                    f"{level_note}"
                )
                send_telegram(chat_id, msg)
        except Exception as e:
            print("❌ ERROR:", e)
            send_telegram(chat_id, "❌ Terjadi kesalahan saat memproses sinyal.")

    Thread(target=handle_signal).start()
    return "ok", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
