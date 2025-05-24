import os
import time
import requests
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()

client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def get_ema(closes, length):
    return sum(closes[-length:]) / length

def get_fibonacci_levels(high, low):
    diff = high - low
    levels = {
        "0.236": high - 0.236 * diff,
        "0.382": high - 0.382 * diff,
        "0.5": high - 0.5 * diff,
        "0.618": high - 0.618 * diff,
        "0.786": high - 0.786 * diff,
    }
    return levels

def trend_direction(symbol, interval):
    try:
        klines = client.futures_klines(symbol=symbol, interval=interval, limit=20)
        closes = [float(k[4]) for k in klines]
        ema4 = get_ema(closes, 4)
        ema20 = get_ema(closes, 20)
        return "UP" if ema4 > ema20 else "DOWN"
    except:
        return "UNKNOWN"

def detect_signal(symbol="BTCUSDT"):
    try:
        klines_1m = client.futures_klines(symbol=symbol, interval="1m", limit=50)
        closes_1m = [float(k[4]) for k in klines_1m]
        volumes_1m = [float(k[5]) for k in klines_1m]

        volume_now = volumes_1m[-1]
        volume_avg = sum(volumes_1m[:-1]) / (len(volumes_1m) - 1)

        if volume_now <= 1.5 * volume_avg:
            print("⏳ Tidak ada volume spike.")
            return

        ema4 = get_ema(closes_1m, 4)
        ema20 = get_ema(closes_1m, 20)
        price_now = closes_1m[-1]

        trend_1m = trend_direction(symbol, "1m")
        trend_5m = trend_direction(symbol, "5m")
        trend_15m = trend_direction(symbol, "15m")

        high = max(closes_1m)
        low = min(closes_1m)
        fib = get_fibonacci_levels(high, low)

        if ema4 > ema20 and trend_1m == trend_5m == trend_15m == "UP":
            signal = "LONG"
        elif ema4 < ema20 and trend_1m == trend_5m == trend_15m == "DOWN":
            signal = "SHORT"
        else:
            signal = "⚠️ Mixed Trend - Wait"

        msg = (
            f"📡 *Sinyal Trading Futures*\n\n"
            f"📊 Pair: `{symbol}`\n"
            f"🕒 Volume Spike: `{volume_now:.2f}` > avg `{volume_avg:.2f}`\n"
            f"📈 EMA(4): `{ema4:.2f}`\n"
            f"📉 EMA(20): `{ema20:.2f}`\n\n"
            f"🧠 Trend:\n"
            f" - 1m: `{trend_1m}`\n"
            f" - 5m: `{trend_5m}`\n"
            f" - 15m: `{trend_15m}`\n\n"
            f"🎯 *Rekomendasi*: *{signal}*\n\n"
            f"📐 Fibonacci:\n"
            f" - 0.236: `{fib['0.236']:.2f}`\n"
            f" - 0.382: `{fib['0.382']:.2f}`\n"
            f" - 0.5: `{fib['0.5']:.2f}`\n"
            f" - 0.618: `{fib['0.618']:.2f}`\n"
            f" - 0.786: `{fib['0.786']:.2f}`"
        )

        send_telegram(msg)
        print("✅ Sinyal dikirim!")
    except Exception as e:
        print(f"❌ Gagal deteksi sinyal: {e}")

while True:
    detect_signal("BTCUSDT")
    time.sleep(60)  # Cek setiap 1 menit
