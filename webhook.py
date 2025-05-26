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
from threading import Thread

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
    payload = {"chat_id": chat_id, "text": message}
    requests.post(url, data=payload)

def send_telegram_photo(chat_id, image_bytes, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", image_bytes)}
    data = {"chat_id": chat_id, "caption": caption}
    requests.post(url, files=files, data=data)

# --- Analysis Tools ---
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

def find_support_demand_levels(prices, window=5, threshold=0.0015):
    """
    Cari support/demand dan resistance berdasarkan local minima/maxima.
    window: jumlah candle untuk cek minima/maxima lokal
    threshold: jarak minimal antar level agar unik
    """
    supports = []
    resistances = []
    length = len(prices)
    for i in range(window, length - window):
        local_min = all(prices[i] <= prices[j] for j in range(i - window, i + window + 1))
        local_max = all(prices[i] >= prices[j] for j in range(i - window, i + window + 1))
        if local_min:
            # cek apakah level ini sudah ada dalam supports ±threshold
            if not any(abs(prices[i] - s) / prices[i] < threshold for s in supports):
                supports.append(prices[i])
        if local_max:
            if not any(abs(prices[i] - r) / prices[i] < threshold for r in resistances):
                resistances.append(prices[i])
    return sorted(supports), sorted(resistances)

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
        return [s["symbol"] for s in info["symbols"]
                if s["contractType"] == "PERPETUAL" and s["symbol"].endswith("USDT")]
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
    data = []
    for k in klines:
        timestamp = pd.to_datetime(k[0], unit='ms')
        data.append([timestamp, float(k[1]), float(k[2]), float(k[3]), float(k[4])])
    df = pd.DataFrame(data, columns=["Date", "Open", "High", "Low", "Close"])
    df.set_index("Date", inplace=True)

    fibo = fibonacci_levels(df["Close"].values)
    prices_fibo = [price for price in fibo.values()]
    colors_fibo = ["g", "b", "r", "y"]

    hlines = dict(
        hlines=prices_fibo,
        colors=colors_fibo,
        linestyle='--',
        linewidths=1,
        alpha=0.7
    )

    fig, axlist = mpf.plot(
        df, type='candle', style='charles',
        hlines=hlines,
        returnfig=True,
        title=f"{symbol} 1h Candlestick + Fibonacci",
        figsize=(10,6)
    )
    ax = axlist[0]
    for price, level, color in zip(prices_fibo, fibo.keys(), colors_fibo):
        ax.text(df.index[-1], price, f"Fib {level}", color=color, fontsize=9,
                verticalalignment='bottom', horizontalalignment='right',
                backgroundcolor='white', alpha=0.6)

    fig.text(0.5, 0.95, "Signal Future Pro", fontsize=14, color="gray",
             ha="center", va="top", alpha=0.3, fontweight='bold')

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
        msg = "✅ Pair Binance Futures:\n" + ", ".join(pairs[:50]) + "..."
        send_telegram(chat_id, msg)
        return "ok", 200

    if text == "PAIRSVOL":
        pairs = get_top_volume_pairs()
        if not pairs:
            send_telegram(chat_id, "⚠️ Gagal mengambil data volume.")
        else:
            send_telegram(chat_id, "🔥 Top 10 Pair Berdasarkan Volume:\n" + "\n".join(pairs))
        return "ok", 200

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

    if text.startswith("CHART "):
        symbol = text.split(" ")[1]
        if not is_valid_futures_symbol(symbol):
            send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan.")
        else:
            img = plot_candlestick_fibonacci_chart(symbol)
            if img is None:
                send_telegram(chat_id, "⚠️ Gagal mengambil data chart.")
            else:
                send_telegram_photo(chat_id, img, caption=f"📊 Chart {symbol} + Fibonacci Support/Resistance")
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
        send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan.")
        return
    signal, price_now, levels, confidence, supports, resistances = analyze_signal(symbol)
    if signal == "NONE":
        msg = f"⚠️ Tidak ada sinyal jelas untuk {symbol}."
    else:
        # Cek proximity harga dengan support/demand dan resistance (±0.5%)
        prox_support = [s for s in supports if abs(price_now - s) / price_now < 0.005]
        prox_resistance = [r for r in resistances if abs(price_now - r) / price_now < 0.005]

        entry_suggestion = ""
        if signal == "LONG":
            if prox_support:
                entry_suggestion = f"💡 Harga dekat support {', '.join(f'{s:.2f}' for s in prox_support)}. Potensi entry LONG bagus."
            elif prox_resistance:
                entry_suggestion = f"⚠️ Harga dekat resistance {', '.join(f'{r:.2f}' for r in prox_resistance)}. Hati-hati entry LONG."
            else:
                entry_suggestion = "💡 Pertimbangkan entry LONG sesuai sinyal."
        elif signal == "SHORT":
            if prox_resistance:
                entry_suggestion = f"💡 Harga dekat resistance {', '.join(f'{r:.2f}' for r in prox_resistance)}. Potensi entry SHORT bagus."
            elif prox_support:
                entry_suggestion = f"⚠️ Harga dekat support {', '.join(f'{s:.2f}' for s in prox_support)}. Hati-hati entry SHORT."
            else:
                entry_suggestion = "💡 Pertimbangkan entry SHORT sesuai sinyal."

        msg = (
            f"📊 Analisis Sinyal untuk {symbol}\n"
            f"➡️ Sinyal: *{signal}*\n"
            f"➡️ Harga Saat Ini: {price_now:.2f}\n"
            f"➡️ Confidence: {confidence*100:.1f}%\n\n"
            f"🔹 Level Fibonacci:\n" +
            "\n".join([f"  - {k}: {v:.2f}" for k,v in levels.items()]) +
            "\n\n" +
            (f"🟢 Support / Demand Area:\n  - " + ", ".join(f"{s:.2f}" for s in supports) if supports else "🟢 Support / Demand Area: Tidak ada.") +
            "\n\n" +
            (f"🔴 Resistance Area:\n  - " + ", ".join(f"{r:.2f}" for r in resistances) if resistances else "🔴 Resistance Area: Tidak ada.") +
            "\n\n" +
            entry_suggestion
        )
        send_telegram(chat_id, msg)

    Thread(target=handle_signal).start()
    return "ok", 200

# --- Main ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
