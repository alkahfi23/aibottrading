# signal_future_pro.py

import os
import json
import time
import requests
import traceback
import pandas as pd
import numpy as np
import ta
import mplfinance as mpf
from flask import Flask, request
from io import BytesIO
from datetime import datetime
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from binance.um_futures import UMFutures

# Load API Keys
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

# Inisialisasi
TELEGRAM_BOT = TeleBot(TELEGRAM_BOT_TOKEN)
BINANCE_CLIENT = UMFutures(key=BINANCE_API_KEY, secret=BINANCE_API_SECRET)

POPULAR_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "MATICUSDT", "DOTUSDT"
]

app = Flask(__name__)

# Fungsi ambil data candlestick
def get_klines(symbol, interval="1m", limit=100):
    try:
        data = BINANCE_CLIENT.klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close',
            'volume', 'close_time', 'quote_asset_volume',
            'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
        ])
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        return df
    except Exception as e:
        print(f"Error get_klines for {symbol}: {e}")
        traceback.print_exc()
        return pd.DataFrame()

# Analisis sinyal LONG/SHORT
def analyze_multi_timeframe(symbol):
    df = get_klines(symbol)
    if df.empty:
        return f"⚠️ Gagal mengambil data untuk {symbol}", None, None

    df["ema20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["ema50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["rsi"] = ta.momentum.rsi(df["close"], window=14)
    df["macd_diff"] = ta.trend.macd_diff(df["close"])

    adx = ta.trend.adx(df["high"], df["low"], df["close"])
    df["adx"] = adx

    latest = df.iloc[-1]
    signal = None

    if (
        latest["ema20"] > latest["ema50"]
        and latest["rsi"] > 50
        and latest["macd_diff"] > 0
        and latest["adx"] > 20
    ):
        signal = "LONG"
    elif (
        latest["ema20"] < latest["ema50"]
        and latest["rsi"] < 50
        and latest["macd_diff"] < 0
        and latest["adx"] > 20
    ):
        signal = "SHORT"

    message = (
        f"*Sinyal {signal} Terdeteksi*\n"
        f"Pair: `{symbol}`\n"
        f"Harga: `{format_price(symbol, latest['close'])}`\n"
        f"RSI: `{latest['rsi']:.2f}` | MACD: `{latest['macd_diff']:.2f}` | ADX: `{latest['adx']:.2f}`\n"
        f"EMA20: `{format_price(symbol, latest['ema20'])}` | EMA50: `{format_price(symbol, latest['ema50'])}`"
    ) if signal else f"Tidak ada sinyal kuat di {symbol} saat ini."

    return message, signal, latest["close"]

# Format harga sesuai pair
def format_price(symbol, price):
    dec = 2 if 'USDT' in symbol else 4
    return f"{price:.{dec}f}"

# Chart candlestick
def generate_chart(symbol, signal, entry_price):
    df = get_klines(symbol)
    if df.empty:
        return None
    df.set_index("timestamp", inplace=True)

    mc = mpf.make_marketcolors(up="g", down="r", inherit=True)
    s = mpf.make_mpf_style(marketcolors=mc)
    title = f"{symbol} - {signal} @ {format_price(symbol, entry_price)}"
    fig, axlist = mpf.plot(df[-60:], type="candle", style=s, title=title,
                           ylabel="Price", volume=True, returnfig=True)
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    return buf

# Webhook untuk menerima perintah Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if "message" in data and "text" in data["message"]:
        text = data["message"]["text"].strip().upper()
        chat_id = data["message"]["chat"]["id"]

        if text in ["LONG", "SHORT"]:
            found = False
            TELEGRAM_BOT.send_message(chat_id, f"🔍 Mencari sinyal `{text}` di 10 coin populer...", parse_mode="Markdown")
            for symbol in POPULAR_SYMBOLS:
                try:
                    message, signal, entry = analyze_multi_timeframe(symbol)
                    if signal == text:
                        TELEGRAM_BOT.send_message(chat_id, message, parse_mode="Markdown")
                        chart = generate_chart(symbol, signal, entry)
                        if chart:
                            TELEGRAM_BOT.send_photo(chat_id, chart)
                        markup = InlineKeyboardMarkup()
                        button = InlineKeyboardButton(
                            text=f"Buka {symbol} di Binance 📲",
                            url=f"https://www.binance.com/en/futures/{symbol}?ref=GRO_16987_24H8Y"
                        )
                        markup.add(button)
                        TELEGRAM_BOT.send_message(chat_id, "Klik tombol di bawah untuk buka di aplikasi Binance:", reply_markup=markup)
                        found = True
                except Exception as e:
                    print(f"Error cek {symbol}: {e}")
                    traceback.print_exc()

            if not found:
                TELEGRAM_BOT.send_message(chat_id, f"❌ Tidak ditemukan sinyal `{text}` saat ini.", parse_mode="Markdown")
    return "OK"

# Endpoint health check
@app.route('/')
def index():
    return "🚀 Signal Bot Aktif!"

# Run lokal
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
