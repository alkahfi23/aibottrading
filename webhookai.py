import os
import time
import requests
import io
import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import openai
from flask import Flask, request
from collections import defaultdict
from threading import Thread
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# --- Konfigurasi ---
BINANCE_BASE = "https://fapi.binance.com"
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT = os.getenv("BOT_CHAT_ID")
openai.api_key = os.getenv("OPENAI_API_KEY")
RATE_LIMIT_SECONDS = 60
last_request_time = defaultdict(lambda: 0)

# --- Tools ---

def send_telegram(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=data)

def send_telegram_photo(chat_id, img_bytes, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": img_bytes}
    data = {"chat_id": chat_id, "caption": caption}
    requests.post(url, data=data, files=files)

def get_klines(symbol, interval="1m", limit=100):
    url = f"{BINANCE_BASE}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=5).json()
        return res if isinstance(res, list) else []
    except:
        return []

def ema(data, period=10):
    data = np.array(data)
    if len(data) < period:
        return data
    return np.convolve(data, np.exp(np.linspace(-1., 0., period)), mode='valid')

def bollinger_bands(data, window=20, num_std=2):
    series = np.array(data[-window:])
    ma = np.mean(series)
    std = np.std(series)
    upper = ma + num_std * std
    lower = ma - num_std * std
    return upper, lower

def fibonacci_levels(data):
    max_price = max(data)
    min_price = min(data)
    diff = max_price - min_price
    levels = {
        "0.0": max_price,
        "0.236": max_price - 0.236 * diff,
        "0.382": max_price - 0.382 * diff,
        "0.5": max_price - 0.5 * diff,
        "0.618": max_price - 0.618 * diff,
        "1.0": min_price,
    }
    return levels

def get_active_futures_pairs():
    url = f"{BINANCE_BASE}/fapi/v1/exchangeInfo"
    data = requests.get(url).json()
    return [s["symbol"] for s in data["symbols"] if s["contractType"] == "PERPETUAL"]

def is_valid_futures_symbol(symbol):
    return symbol in get_active_futures_pairs()

def get_top_volume_pairs():
    url = f"{BINANCE_BASE}/fapi/v1/ticker/24hr"
    try:
        data = requests.get(url, timeout=5).json()
        filtered = [d for d in data if d["symbol"].endswith("USDT")]
        sorted_data = sorted(filtered, key=lambda x: float(x["quoteVolume"]), reverse=True)
        return [f"{d['symbol']} (${float(d['quoteVolume'])/1e6:.1f}M)" for d in sorted_data[:10]]
    except:
        return []

def detect_support_resistance():
    symbols = get_top_volume_pairs()
    results_support, results_resistance = [], []
    for entry in symbols:
        symbol = entry.split(" ")[0]
        klines = get_klines(symbol, "1h")
        closes = [float(k[4]) for k in klines]
        price_now = closes[-1]
        levels = fibonacci_levels(closes)
        fib_support = levels["0.618"]
        fib_resist = levels["0.236"]
        if abs(price_now - fib_support) / fib_support < 0.003:
            results_support.append((symbol, price_now, fib_support))
        if abs(price_now - fib_resist) / fib_resist < 0.003:
            results_resistance.append((symbol, price_now, fib_resist))
    return results_support, results_resistance

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
        if ema4[-1] > ema20[-1] and price_now > upper:
            trend["LONG"] += 1
        elif ema4[-1] < ema20[-1] and price_now < lower:
            trend["SHORT"] += 1
        if tf == "1h":
            levels = fibonacci_levels(closes)

    signal = "LONG" if trend["LONG"] >= 2 else "SHORT" if trend["SHORT"] >= 2 else "NONE"
    confidence = max(trend["LONG"], trend["SHORT"]) / 4
    return signal, price_now, levels, confidence

def analyze_ai(symbol):
    signal, price_now, levels, confidence = analyze_signal(symbol)
    trend_direction = "naik (bullish)" if signal == "LONG" else "turun (bearish)" if signal == "SHORT" else "tidak jelas"

    prompt = (
        f"Saya adalah bot analis trading crypto. Berikut data untuk simbol {symbol}:\n"
        f"- Harga saat ini: {price_now:.2f}\n"
        f"- Prediksi tren: {trend_direction}\n"
        f"- Confidence: {confidence*100:.1f}%\n"
        f"- Level Fibonacci:\n" +
        "\n".join([f"  - {k}: {v:.2f}" for k, v in levels.items()]) +
        "\nBerikan analisa singkat dan saran entry (LONG/SHORT), target, dan risiko secara profesional."
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",  # atau gpt-3.5-turbo
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.5,
        )
        reply = response.choices[0].message["content"]
    except Exception as e:
        reply = f"⚠️ Gagal menganalisis AI: {e}"

    return f"🤖 *Analisa AI {symbol}*\n\n{reply}"


def plot_candlestick_fibonacci_chart(symbol):
    klines = get_klines(symbol, "15m", 100)
    if not klines:
        return None
    closes = [float(k[4]) for k in klines]
    dates = [datetime.fromtimestamp(k[0]/1000) for k in klines]
    opens = [float(k[1]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]

    fig, ax = plt.subplots(figsize=(10,5))
    for i in range(len(dates)):
        color = 'green' if closes[i] >= opens[i] else 'red'
        ax.plot([dates[i], dates[i]], [lows[i], highs[i]], color=color)
        ax.plot([dates[i], dates[i]], [opens[i], closes[i]], linewidth=6, color=color)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    ax.set_title(f"{symbol} Candlestick + Fibonacci")
    
    levels = fibonacci_levels(closes)
    for k, v in levels.items():
        ax.axhline(y=v, linestyle='--', label=f'Fib {k}', linewidth=1)
    ax.legend()
    
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)
    return buf

# --- Webhook ---
@app.route("/", methods=["POST"])
def webhook():
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
        send_telegram(chat_id, "🔥 Top Volume:\n" + "\n".join(pairs))
        return "ok", 200

    if text == "PAIRSUP" or text == "PAIREST":
        support, resistance = detect_support_resistance()
        if text == "PAIRSUP":
            msg = "🟢 Pair Dekat Support:\n" + "\n".join([f"{s[0]}: {s[1]:.2f}" for s in support]) or "Tidak ada."
        else:
            msg = "🔴 Pair Dekat Resistance:\n" + "\n".join([f"{s[0]}: {s[1]:.2f}" for s in resistance]) or "Tidak ada."
        send_telegram(chat_id, msg)
        return "ok", 200

    if text.startswith("CHART "):
        symbol = text.split(" ")[1]
        if not is_valid_futures_symbol(symbol):
            send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan.")
        else:
            img = plot_candlestick_fibonacci_chart(symbol)
            if img:
                send_telegram_photo(chat_id, img, caption=f"📊 Chart {symbol}")
        return "ok", 200

    if text.startswith("TANYA "):
        symbol = text.split(" ")[1]
        if not is_valid_futures_symbol(symbol):
            send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan.")
        else:
            msg = analyze_ai(symbol)
            send_telegram(chat_id, msg)
        return "ok", 200

    if not text.isalnum() or len(text) < 6:
        return "ok", 200

    now = time.time()
    if now - last_request_time[chat_id] < RATE_LIMIT_SECONDS:
        send_telegram(chat_id, "⏳ Tunggu 1 menit sebelum permintaan selanjutnya.")
        return "ok", 200
    last_request_time[chat_id] = now

    def handle_signal():
        symbol = text
        if not is_valid_futures_symbol(symbol):
            send_telegram(chat_id, f"⚠️ Symbol `{symbol}` tidak ditemukan.")
            return
        signal, price_now, levels, confidence = analyze_signal(symbol)
        if signal == "NONE":
            msg = f"⚠️ Tidak ada sinyal jelas untuk {symbol}."
        else:
            msg = (
                f"📈 Sinyal {signal} untuk {symbol}\n"
                f"Harga: {price_now:.2f}\n"
                f"Confidence: {confidence*100:.1f}%\n" +
                "\n".join([f"  - {k}: {v:.2f}" for k, v in levels.items()])
            )
        send_telegram(chat_id, msg)

    Thread(target=handle_signal).start()
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
