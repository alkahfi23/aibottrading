from flask import Flask, request
import os
import pandas as pd
import numpy as np
import ta
import telebot
from datetime import datetime
from binance.client import Client
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from chart_generator import generate_chart  # Pastikan ini tersedia

app = Flask(__name__)

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

def analyze_multi_timeframe(symbol):
    df_15m = get_klines(symbol, interval="15m", limit=100)
    df_5m = get_klines(symbol, interval="5m", limit=100)
    df_1m = get_klines(symbol, interval="1m", limit=100)

    if df_15m is None or df_5m is None or df_1m is None:
        return "📉 Data tidak lengkap untuk analisis multi-timeframe.", "NONE", None

    # TF Utama - 15M (Trend)
    df_15m['EMA50'] = ta.trend.ema_indicator(df_15m['close'], window=50)
    df_15m['EMA200'] = ta.trend.ema_indicator(df_15m['close'], window=200)
    trend_utama = "Bullish" if df_15m['EMA50'].iloc[-1] > df_15m['EMA200'].iloc[-1] else "Bearish"

    # Konfirmasi - 5M
    df_5m['RSI'] = ta.momentum.rsi(df_5m['close'], window=14)
    macd = ta.trend.MACD(df_5m['close'])
    df_5m['MACD'] = macd.macd()
    df_5m['MACD_SIGNAL'] = macd.macd_signal()
    df_5m['ADX'] = ta.trend.adx(df_5m['high'], df_5m['low'], df_5m['close'], window=14)
    df_5m['VolumeSpike'] = df_5m['volume'] > df_5m['volume'].rolling(window=20).mean() * 1.5
    last_5m = df_5m.iloc[-1]

    # Entry: 1M - Berdasarkan BB dan RSI
    df_1m['RSI'] = ta.momentum.rsi(df_1m['close'], window=14)
    bb = ta.volatility.BollingerBands(df_1m['close'])
    df_1m['BB_L'] = bb.bollinger_lband()
    df_1m['BB_H'] = bb.bollinger_hband()

    last = df_1m.iloc[-1]
    prev = df_1m.iloc[-2]
    signal = "NONE"
    entry = stop_loss = take_profit = None

    if last['close'] < last['BB_L'] and last['RSI'] < 30:
        signal = "LONG"
        entry = last['close']
        stop_loss = prev['low']  # SL di BB paling bawah sebelumnya
        take_profit = "Sampai muncul sinyal SHORT"
    elif last['close'] > last['BB_H'] and last['RSI'] > 70:
        signal = "SHORT"
        entry = last['close']
        stop_loss = prev['high']  # SL di BB paling atas sebelumnya
        take_profit = "Sampai muncul sinyal LONG"

    current_price = last['close']

    def format_price(p):
        if p is None:
            return "-"
        dec = 8 if 'USDT' in symbol else 4
        return f"{p:.{dec}f}"

    result = f"""
📊 Pair: {symbol}
⏰ TF Utama: 15M | Konfirmasi: 5M | Entry: 1M

📈 Trend 15M: {trend_utama}
📌 RSI 5M: {round(last_5m['RSI'], 1)}
📌 MACD: {'Bullish' if last_5m['MACD'] > last_5m['MACD_SIGNAL'] else 'Bearish'}
📌 ADX: {round(last_5m['ADX'], 1)}
📌 Volume Spike: {'Ya' if last_5m['VolumeSpike'] else 'Tidak'}

📄 Sinyal Final: {'✅ ' + signal if signal != 'NONE' else '⛔ Tidak valid'}
💰 Harga Saat Ini: ${format_price(current_price)}
"""

    if signal != "NONE":
        result += f"""
🎯 Entry: {format_price(entry)}
🛡️ Stop Loss: {format_price(stop_loss)}
🎯 Take Profit: {take_profit}
"""
    return result.strip(), signal, entry

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
                TELEGRAM_BOT.send_message(chat_id, f"Error analisis: {e}")
        else:
            TELEGRAM_BOT.send_message(chat_id, "Format simbol tidak valid atau terlalu pendek.")
    return "OK"

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
