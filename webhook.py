import os
import requests
import numpy as np
import time
import matplotlib.pyplot as plt
import io
import pandas as pd
import mplfinance as mpf
from flask import Flask, request
from binance.client import Client
from collections import defaultdict

app = Flask(__name__)

# --- ENV ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
last_request_time = defaultdict(float)
RATE_LIMIT_SECONDS = 60

# --- Telegram ---
def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    requests.post(url, data=payload)

def send_telegram_photo(chat_id, image_bytes, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", image_bytes)}
    data = {"chat_id": chat_id, "caption": caption}
    requests.post(url, files=files, data=data)

# --- Tools ---
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

def find_support_demand_levels(prices, window=5, threshold=0.0015):
    supports = []
    resistances = []
    for i in range(window, len(prices) - window):
        if all(prices[i] <= prices[j] for j in range(i - window, i + window + 1)):
            if not any(abs(prices[i] - s) / prices[i] < threshold for s in supports):
                supports.append(prices[i])
        if all(prices[i] >= prices[j] for j in range(i - window, i + window + 1)):
            if not any(abs(prices[i] - r) / prices[i] < threshold for r in resistances):
                resistances.append(prices[i])
    return sorted(supports), sorted(resistances)

def is_valid_futures_symbol(symbol):
    try:
        info = client.futures_exchange_info()
        return symbol.upper() in [s["symbol"] for s in info["symbols"]]
    except:
        return False

def analyze_signal(symbol):
    trend = {"LONG": 0, "SHORT": 0}
    levels = {}
    price_now = 0
    support_levels = []
    resistance_levels = []

    for tf in ["1m", "5m", "15m", "1h"]:
        klines = get_klines(symbol, tf)
        if not klines:
            continue
        closes = [float(k[4]) for k in klines]
        price_now = closes[-1]
        ema4 = ema(closes, 4)
        ema20 = ema(closes, 20)

        if ema4 > ema20 and price_now > ema20:
            trend["LONG"] += 1
        elif ema4 < ema20 and price_now < ema20:
            trend["SHORT"] += 1

        if tf == "1h":
            levels = fibonacci_levels(closes)
            support_levels, resistance_levels = find_support_demand_levels(closes)

    signal = "LONG" if trend["LONG"] >= 2 else "SHORT" if trend["SHORT"] >= 2 else "NONE"
    confidence = max(trend["LONG"], trend["SHORT"]) / 4
    return signal, price_now, levels, confidence, support_levels, resistance_levels

def get_active_futures_pairs():
    try:
        info = client.futures_exchange_info()
        return [s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL" and s["symbol"].endswith("USDT")]
    except:
        return []

def get_top_volume_pairs():
    try:
        tickers = client.futures_ticker()
        usdt_pairs = [t for t in tickers if t["symbol"].endswith("USDT")]
        sorted_by_vol = sorted(usdt_pairs, key=lambda x: float(x["quoteVolume"]), reverse=True)
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

def plot_candlestick_fibonacci_chart(symbol):
    klines = get_klines(symbol, "1h", 100)
    if not klines:
        return None
    data = [[pd.to_datetime(k[0], unit='ms'), float(k[1]), float(k[2]), float(k[3]), float(k[4])] for k in klines]
    df = pd.DataFrame(data, columns=["Date", "Open", "High", "Low", "Close"]).set_index("Date")

    fibo = fibonacci_levels(df["Close"].values)
    prices_fibo = list(fibo.values())
    colors_fibo = ["g", "b", "r", "y"]

    fig, axlist = mpf.plot(df, type='candle', style='charles', hlines=dict(
        hlines=prices_fibo, colors=colors_fibo, linestyle='--', linewidths=1, alpha=0.7
    ), returnfig=True, title=f"{symbol} 1h Candlestick + Fibonacci", figsize=(10, 6))

    for price, level, color in zip(prices_fibo, fibo.keys(), colors_fibo):
        axlist[0].text(df.index[-1], price, f"Fib {level}", color=color, fontsize=9,
                       verticalalignment='bottom', horizontalalignment='right',
                       backgroundcolor='white', alpha=0.6)

    fig.text(0.5, 0.95, "Signal Future Pro", fontsize=14, color="gray", ha="center", va="top", alpha=0.3, fontweight='bold')
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    buf.seek(0)
    plt.close(fig)
    return buf

# --- Webhook ---
@app.route("/<path:token>", methods=["GET", "POST"])
def webhook_token(token):
    if token != TELEGRAM_TOKEN:
        return "Unauthorized", 403
    if request.method == "GET":
        return "OK", 200

    data = request.get_json()
    if "message" not in data:
        return "ok", 200

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "").strip().upper()

    if text == "PAIRS":
        pairs = get_active_futures_pairs()
        send_telegram(chat_id, "✅ Pair Binance Futures:\n" + ", ".join(pairs[:50]) + "...")
        return "ok", 200

    if text == "PAIRSVOL":
        pairs = get_top_volume_pairs()
        msg = "🔥 Top 10 Pair Berdasarkan Volume:\n" + "\n".join(pairs) if pairs else "⚠️ Gagal mengambil data volume."
        send_telegram(chat_id, msg)
        return "ok", 200

    if text == "PAIRSUP" or text == "PAIREST":
        support, resistance = detect_support_resistance()
        if text == "PAIRSUP":
            msg = "🟢 Pair Dekat Support (±0.3% dari Fib 0.618):\n" + "\n".join(
                [f"• {s[0]}: {s[1]:.2f} (Support: {s[2]:.2f})" for s in support]) or "Tidak ada."
        else:
            msg = "🔴 Pair Dekat Resistance (±0.3% dari Fib 0.236):\n" + "\n".join(
                [f"• {s[0]}: {s[1]:.2f} (Resistance: {s[2]:.2f})" for s in resistance]) or "Tidak ada."
        send_telegram(chat_id, msg)
        return "ok", 200

    if text.startswith("CHART "):
        symbol = text.split(" ")[1]
        if not is_valid_futures_symbol(symbol):
            send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan.")
        else:
            img = plot_candlestick_fibonacci_chart(symbol)
            if img:
                send_telegram_photo(chat_id, img, caption=f"📊 Chart {symbol} + Fibonacci Support/Resistance")
            else:
                send_telegram(chat_id, "⚠️ Gagal mengambil data chart.")
        return "ok", 200

    if not text.isalnum() or len(text) < 6:
        return "ok", 200

    now = time.time()
    if now - last_request_time[chat_id] < RATE_LIMIT_SECONDS:
        send_telegram(chat_id, "⏳ Tunggu sebentar ya, coba lagi 1 menit lagi.")
        return "ok", 200
    last_request_time[chat_id] = now

    # --- Handle Signal Analysis ---
    symbol = text
    if not is_valid_futures_symbol(symbol):
        send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan.")
        return "ok", 200

    signal, price_now, levels, confidence, supports, resistances = analyze_signal(symbol)
    if signal == "NONE":
        send_telegram(chat_id, f"⚠️ Tidak ada sinyal jelas untuk {symbol}.")
    else:
        prox_support = [s for s in supports if abs(price_now - s) / price_now < 0.005]
        prox_resistance = [r for r in resistances if abs(price_now - r) / price_now < 0.005]

        if signal == "LONG":
            entry_msg = "💡 Harga dekat support." if prox_support else "⚠️ Dekat resistance." if prox_resistance else "💡 Sinyal LONG aktif."
        else:
            entry_msg = "💡 Harga dekat resistance." if prox_resistance else "⚠️ Dekat support." if prox_support else "💡 Sinyal SHORT aktif."

        msg = (
            f"📊 *Analisis Sinyal untuk {symbol}*\n"
            f"➡️ *Sinyal:* {signal}\n"
            f"➡️ *Harga Saat Ini:* {price_now:.2f}\n"
            f"➡️ *Confidence:* {confidence*100:.1f}%\n\n"
            f"🔹 *Level Fibonacci:*\n" + "\n".join([f"  - {k}: {v:.2f}" for k,v in levels.items()]) +
            "\n\n" +
            (f"🟢 *Support:*\n" + ", ".join(f"{s:.2f}" for s in supports) if supports else "🟢 Tidak ada support.") +
            "\n" +
            (f"🔴 *Resistance:*\n" + ", ".join(f"{r:.2f}" for r in resistances) if resistances else "🔴 Tidak ada resistance.") +
            "\n\n" +
            entry_msg
        )
        send_telegram(chat_id, msg)
    return "ok", 200

# --- Start App ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
