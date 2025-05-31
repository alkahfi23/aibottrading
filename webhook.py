from flask import Flask, request
import os
import pandas as pd
import numpy as np
import ta
import telebot
from datetime import datetime
from binance.client import Client
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from chart_generator import generate_chart  # Pastikan file ini tersedia dan berfungsi

app = Flask(__name__)

# Load environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

POPULAR_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "DOTUSDT", "MATICUSDT"
]

def get_klines(symbol, interval="5m", limit=100):
    try:
        raw = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        if not raw:
            return None
        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df.astype(float)
        return df[['open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        print(f"Error get_klines ({interval}): {e}")
        return None

# Ganti fungsi ini
def detect_reversal_candle(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    body = abs(last['close'] - last['open'])
    upper_shadow = last['high'] - max(last['close'], last['open'])
    lower_shadow = min(last['close'], last['open']) - last['low']
    
    body_ratio = body / (last['high'] - last['low'] + 1e-6)

    # Hammer (bodi kecil di atas dengan sumbu bawah panjang)
    if body_ratio < 0.3 and lower_shadow > 2 * body and upper_shadow < body:
        return "Hammer"

    # Inverted Hammer (bodi kecil di bawah dengan sumbu atas panjang)
    if body_ratio < 0.3 and upper_shadow > 2 * body and lower_shadow < body:
        return "InvertedHammer"

    # Bullish Engulfing (bodi hijau lebih besar dan menutupi merah sebelumnya)
    if prev['close'] < prev['open'] and last['close'] > last['open'] and \
       last['open'] < prev['close'] and last['close'] > prev['open']:
        return "Engulfing"

    # Shooting Star (bodi kecil di bawah dengan sumbu atas panjang)
    if body_ratio < 0.3 and upper_shadow > 2 * body and lower_shadow < body:
        return "ShootingStar"

    return None

def analyze_multi_timeframe(symbol):
    df_15m = get_klines(symbol, '15m', 500)
    df_5m = get_klines(symbol, '5m', 500)
    df_1m = get_klines(symbol, '1m', 500)

    if df_1m is None or df_5m is None or df_15m is None:
        raise ValueError("Gagal mengambil data untuk salah satu timeframe.")

    for df in [df_15m, df_5m, df_1m]:
        df['EMA20'] = df['close'].ewm(span=20).mean()
        df['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
        bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
        df['BB_H'] = bb.bollinger_hband()
        df['BB_L'] = bb.bollinger_lband()

    signal = None
    entry = None
    stop_loss = None
    take_profit = None
    current_price = df_1m['close'].iloc[-1]
    candle_pattern = detect_reversal_candle(df_1m)

    trend_15m = "UP" if df_15m['close'].iloc[-1] > df_15m['EMA20'].iloc[-1] else "DOWN"
    trend_5m = "UP" if df_5m['close'].iloc[-1] > df_5m['EMA20'].iloc[-1] else "DOWN"
    last = df_1m.iloc[-1]

    if trend_15m == "UP" and trend_5m == "UP":
        if last['RSI'] < 30 and last['close'] < last['BB_L'] and candle_pattern in ['Hammer', 'InvertedHammer', 'Engulfing']:
            signal = "LONG"
            entry = current_price
            prev_below_bb = df_1m[:-1][df_1m['close'] < df_1m['BB_L']]
            stop_loss = prev_below_bb['low'].iloc[-1] if not prev_below_bb.empty else df_1m['low'].min()
            risk = entry - stop_loss
            take_profit = entry + (2 * risk)

    elif trend_15m == "DOWN" and trend_5m == "DOWN":
        if last['RSI'] > 70 and last['close'] > last['BB_H'] and candle_pattern in ['ShootingStar', 'Engulfing']:
            signal = "SHORT"
            entry = current_price
            prev_above_bb = df_1m[:-1][df_1m['close'] > df_1m['BB_H']]
            stop_loss = prev_above_bb['high'].iloc[-1] if not prev_above_bb.empty else df_1m['high'].max()
            risk = stop_loss - entry
            take_profit = entry - (2 * risk)

    result = f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}\n"
    result += f"📉 Pair: {symbol}\n"
    result += f"Trend 15m: {trend_15m}\n"
    result += f"Trend 5m: {trend_5m}\n"
    result += f"🕯️ RSI 1m: {last['RSI']:.2f}\n"
    result += f"📊 Harga Sekarang: {current_price:.2f}\n"
    result += f"🕯️ Pola Candle Terbaca: `{candle_pattern or 'Tidak ada'}`\n"

    if signal:
        result += f"\n✅ Sinyal Terdeteksi: {signal}\n"
        result += f"🎯 Entry: {entry:.2f}\n"
        result += f"🛑 Stop Loss: {stop_loss:.2f}\n"
        result += f"🎯 Take Profit: {take_profit:.2f}\n"
    else:
        result += "\n🚫 Tidak ada sinyal valid saat ini."

    return result, signal or "NONE", entry or 0

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
                            TELEGRAM_BOT.send_photo(chat_id=chat_id, photo=chart)
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

            if not found:
                TELEGRAM_BOT.send_message(chat_id, f"❌ Tidak ditemukan sinyal `{text}` saat ini.", parse_mode="Markdown")
            return "OK"

        # Cek simbol langsung seperti BTCUSDT
        if len(text) >= 6 and text.isalnum():
            try:
                message, signal, entry = analyze_multi_timeframe(text)
                TELEGRAM_BOT.send_message(chat_id, message, parse_mode="Markdown")

                if signal != "NONE":
                    chart = generate_chart(text, signal, entry)
                    if chart:
                        TELEGRAM_BOT.send_photo(chat_id, chart)

                    markup = InlineKeyboardMarkup()
                    button = InlineKeyboardButton(
                        text=f"Buka {text} di Binance 📲",
                        url=f"https://www.binance.com/en/futures/{text}?ref=GRO_16987_24H8Y"
                    )
                    markup.add(button)
                    TELEGRAM_BOT.send_message(chat_id, "Klik tombol di bawah untuk buka di aplikasi Binance:", reply_markup=markup)
            except Exception as e:
                TELEGRAM_BOT.send_message(chat_id, f"⚠️ Error analisis: {e}")
        else:
            TELEGRAM_BOT.send_message(chat_id, "⚠️ Format simbol tidak valid atau terlalu pendek.")
    return "OK"

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
