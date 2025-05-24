import os
import time
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
import requests
from binance.client import Client
from binance.enums import *

# === KONFIGURASI ===
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(API_KEY, API_SECRET)

# === TOOLS ===
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"❌ Gagal kirim Telegram: {e}")

def get_ema(prices, period):
    if len(prices) < period:
        return sum(prices) / len(prices)
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema

def get_fibonacci_levels(high, low):
    diff = high - low
    return {
        '0.0': high,
        '0.236': high - 0.236 * diff,
        '0.382': high - 0.382 * diff,
        '0.5': high - 0.5 * diff,
        '0.618': high - 0.618 * diff,
        '0.786': high - 0.786 * diff,
        '1.0': low
    }

def analyze_symbol(symbol):
    try:
        # Ambil data 1m, 5m, 15m
        k1 = client.futures_klines(symbol=symbol, interval='1m', limit=50)
        k5 = client.futures_klines(symbol=symbol, interval='5m', limit=50)
        k15 = client.futures_klines(symbol=symbol, interval='15m', limit=50)

        # Harga penutupan
        close1 = [float(k[4]) for k in k1]
        close5 = [float(k[4]) for k in k5]
        close15 = [float(k[4]) for k in k15]

        # EMA untuk 1m
        ema4_1m = get_ema(close1[-10:], 4)
        ema20_1m = get_ema(close1[-20:], 20)

        # Validasi multi TF
        trend1 = 'LONG' if ema4_1m > ema20_1m else 'SHORT'
        trend5 = 'LONG' if get_ema(close5[-10:], 4) > get_ema(close5[-20:], 20) else 'SHORT'
        trend15 = 'LONG' if get_ema(close15[-10:], 4) > get_ema(close15[-20:], 20) else 'SHORT'

        # Ambil harga sekarang
        mark_price = float(client.futures_mark_price(symbol=symbol)['markPrice'])

        # Fibonacci dari 50 candle terakhir (1m)
        high = max([float(k[2]) for k in k1])
        low = min([float(k[3]) for k in k1])
        fib = get_fibonacci_levels(high, low)

        recommendation = f"Multi-TF: {trend1}/{trend5}/{trend15}, Fib: R={fib['0.236']:.2f}, S={fib['0.786']:.2f}"

        # Kirim sinyal jika semua timeframe sinkron
        if trend1 == trend5 == trend15:
            send_signal_notification(symbol, trend1, mark_price, recommendation)

    except Exception as e:
        print(f"❌ Gagal analisa {symbol}: {e}")

def send_signal_notification(symbol, signal, mark_price, recommendation):
    text = f"""
📊 <b>Sinyal Futures Terdeteksi!</b>
Symbol: <b>{symbol}</b>
Sinyal: <b>{'🚀 LONG' if signal == 'LONG' else '🔻 SHORT'}</b>
Harga Saat Ini: <b>${mark_price:,.2f}</b>
Rekomendasi: <i>{recommendation}</i>
Waktu: <i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>
""".strip()
    send_telegram(text)

# === MAIN LOOP 24/7 ===
if __name__ == '__main__':
    symbols = ['BTCUSDT', 'ETHUSDT']
    print("🚀 Bot berjalan 24/7...")
    while True:
        for sym in symbols:
            analyze_symbol(sym)
        time.sleep(60)  # cek tiap 1 menit
