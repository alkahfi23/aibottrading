from flask import Flask, request
import os
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import numpy as np
import ta
import telebot
from datetime import datetime
from binance.client import Client
from io import BytesIO
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

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

def get_klines(symbol, interval="1m", limit=100):
    try:
        data = client.klines(symbol=symbol, interval=interval, limit=limit)
        if not data:
            raise ValueError("Klines kosong")
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
        print(f"[get_klines] Error ambil data untuk {symbol}: {e}")
        return pd.DataFrame()

def analyze_multi_timeframe(symbol):
    df_4h = get_klines(symbol, interval="4h", limit=100)
    df_1h = get_klines(symbol, interval="1h", limit=100)
    df_5m = get_klines(symbol, interval="5m", limit=100)

    if df_4h is None or df_1h is None or df_5m is None:
        return "📉 Data tidak lengkap untuk analisis multi-timeframe.", "NONE", None

    df_4h['EMA50'] = ta.trend.ema_indicator(df_4h['close'], window=50)
    df_4h['EMA200'] = ta.trend.ema_indicator(df_4h['close'], window=200)
    long_term_trend = "Bullish" if df_4h['EMA50'].iloc[-1] > df_4h['EMA200'].iloc[-1] else "Bearish"

    df_1h['RSI'] = ta.momentum.rsi(df_1h['close'], window=14)
    macd = ta.trend.MACD(df_1h['close'])
    df_1h['MACD'] = macd.macd()
    df_1h['MACD_SIGNAL'] = macd.macd_signal()
    df_1h['ADX'] = ta.trend.adx(df_1h['high'], df_1h['low'], df_1h['close'], window=14)

    df_1h['VolumeSpike'] = df_1h['volume'] > df_1h['volume'].rolling(window=20).mean() * 1.5

    last_1h = df_1h.iloc[-1]
    signal = "NONE"

    if long_term_trend == "Bullish" and last_1h['MACD'] > last_1h['MACD_SIGNAL'] and last_1h['RSI'] > 50:
        signal = "LONG"
    elif long_term_trend == "Bearish" and last_1h['MACD'] < last_1h['MACD_SIGNAL'] and last_1h['RSI'] < 50:
        signal = "SHORT"

    bb_5m = ta.volatility.BollingerBands(df_5m['close'])
    df_5m['BB_L'] = bb_5m.bollinger_lband()
    df_5m['BB_H'] = bb_5m.bollinger_hband()

    entry = None
    stop_loss = None
    take_profit = None

    if signal == "LONG":
        entry = df_5m['BB_L'].iloc[-1]
        stop_loss = entry * 0.985
        take_profit = entry + (entry - stop_loss) * 1.5
    elif signal == "SHORT":
        entry = df_5m['BB_H'].iloc[-1]
        stop_loss = entry * 1.015
        take_profit = entry - (stop_loss - entry) * 1.5

    current_price = df_1h['close'].iloc[-1]

    def format_price(p):
        if p is None:
            return "-"
        dec = 8 if 'USDT' in symbol else 4
        return f"{p:.{dec}f}"

    result = f"""
📊 Pair: {symbol}
⏰ TF Utama: 4H | Konfirmasi: 1H | Entry: 5M

📈 Trend 4H: {long_term_trend}
📌 RSI 1H: {round(last_1h['RSI'],1)}
📌 MACD: {'Bullish' if last_1h['MACD'] > last_1h['MACD_SIGNAL'] else 'Bearish'}
📌 ADX: {round(last_1h['ADX'],1)}
📌 Volume Spike: {'Ya' if last_1h['VolumeSpike'] else 'Tidak'}

📄 Sinyal Final: {'✅ ' + signal if signal != 'NONE' else '⛔ Tidak valid'}
💰 Harga Saat Ini: ${format_price(current_price)}
"""

    if signal != "NONE":
        result += f"""
🎯 Entry (BB 5M): {format_price(entry)}
🛡️ Stop Loss: {format_price(stop_loss)}
🎯 Take Profit: {format_price(take_profit)}
"""

    return result.strip(), signal, entry

def generate_chart(symbol, signal, entry_price):
    df = get_klines(symbol)
    
    # Validasi: Data kosong atau terlalu sedikit
    if df.empty or len(df) < 20:
        print(f"[generate_chart] Tidak cukup data untuk {symbol}")
        return None

    df.set_index("timestamp", inplace=True)

    try:
        mc = mpf.make_marketcolors(up="g", down="r", inherit=True)
        s = mpf.make_mpf_style(marketcolors=mc)
        title = f"{symbol} - {signal} @ {format_price(symbol, entry_price)}"
        fig, axlist = mpf.plot(
            df[-60:], type="candle", style=s, title=title,
            ylabel="Price", volume=True, returnfig=True
        )
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"[generate_chart] Error plot chart {symbol}: {e}")
        traceback.print_exc()
        return None


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
