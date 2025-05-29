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

def get_klines(symbol, interval="5m", limit=100):
    try:
        raw = client.get_klines(symbol=symbol, interval=interval, limit=limit)
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
        print(f"❌ Error get_klines ({interval}): {e}")
        return None

def analyze_multi_timeframe(symbol):
    df_4h = get_klines(symbol, interval="4h", limit=100)
    df_1h = get_klines(symbol, interval="1h", limit=100)
    df_5m = get_klines(symbol, interval="5m", limit=100)

    if df_4h is None or df_1h is None or df_5m is None:
        return "📉 Data tidak lengkap untuk analisis multi-timeframe.", "NONE"

    df_4h['EMA50'] = ta.trend.ema_indicator(df_4h['close'], window=50)
    df_4h['EMA200'] = ta.trend.ema_indicator(df_4h['close'], window=200)
    long_term_trend = "Bullish" if df_4h['EMA50'].iloc[-1] > df_4h['EMA200'].iloc[-1] else "Bearish"

    df_1h['RSI'] = ta.momentum.rsi(df_1h['close'], window=14)
    macd = ta.trend.MACD(df_1h['close'])
    df_1h['MACD'] = macd.macd()
    df_1h['MACD_SIGNAL'] = macd.macd_signal()
    df_1h['ADX'] = ta.trend.adx(df_1h['high'], df_1h['low'], df_1h['close'], window=14)

    last_1h = df_1h.iloc[-1]
    signal = "NONE"

    if long_term_trend == "Bullish" and last_1h['MACD'] > last_1h['MACD_SIGNAL'] and last_1h['RSI'] > 50:
        signal = "LONG"
    elif long_term_trend == "Bearish" and last_1h['MACD'] < last_1h['MACD_SIGNAL'] and last_1h['RSI'] < 50:
        signal = "SHORT"

    bb_5m = ta.volatility.BollingerBands(df_5m['close'])
    df_5m['BB_L'] = bb_5m.bollinger_lband()
    df_5m['BB_H'] = bb_5m.bollinger_hband()

    entry = "-"
    if signal == "LONG":
        entry = df_5m['BB_L'].iloc[-1]
    elif signal == "SHORT":
        entry = df_5m['BB_H'].iloc[-1]

    support = df_1h['low'][-20:].min()
    resistance = df_1h['high'][-20:].max()
    current_price = df_1h['close'].iloc[-1]

    def format_price(p):
        if p == "-":
            return "-"
        dec = 8 if 'USDT' in symbol else 4
        return f"{p:.{dec}f}"

    result = f"""
📊 Pair: {symbol}
⏰ TF Utama: 4H | Konfirmasi: 1H | Entry: 5M

📈 Trend 4H: {long_term_trend}
📌 RSI 1H: {round(last_1h['RSI'],1)}
📌 MACD: {"Bullish" if last_1h['MACD'] > last_1h['MACD_SIGNAL'] else "Bearish"}
📌 ADX: {round(last_1h['ADX'],1)}

📤 Sinyal Final: {'✅ ' + signal if signal != 'NONE' else '⛔ Tidak valid'}
💰 Harga Saat Ini: ${format_price(current_price)}
"""

    if signal != "NONE":
        result += f"""
🎯 Entry (BB 5M): {format_price(entry)}
🛡️ Stop Loss: {format_price(support)}
🎯 Take Profit: {format_price(resistance)}
"""

    return result.strip(), signal

def generate_chart(symbol, signal_type="NONE"):
    try:
        df = get_klines(symbol, interval="1h", limit=100)
        if df is None or df.empty:
            print("⚠️ Chart: Data kosong")
            return None

        df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50)
        df['EMA200'] = ta.trend.ema_indicator(df['close'], window=200)
        last_price = df['close'].iloc[-1]

        addplot = [
            mpf.make_addplot(df['EMA50'], color='green'),
            mpf.make_addplot(df['EMA200'], color='red')
        ]

        if signal_type == "LONG":
            addplot.append(mpf.make_addplot([np.nan]*(len(df)-1) + [last_price * 0.995],
                                            type='scatter', markersize=100, marker='^', color='green'))
        elif signal_type == "SHORT":
            addplot.append(mpf.make_addplot([np.nan]*(len(df)-1) + [last_price * 1.005],
                                            type='scatter', markersize=100, marker='v', color='red'))

        fig, ax = mpf.plot(
            df, type='candle', style='yahoo', addplot=addplot,
            volume=True, returnfig=True, figsize=(8, 6),
            title=f"{symbol} - Signal Future Pro"
        )
        ax[0].text(0.02, 0.95, "Signal Future Pro", transform=ax[0].transAxes,
                   fontsize=14, fontweight='bold', color='blue',
                   bbox=dict(facecolor='white', alpha=0.7))

        buf = BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"❌ Error generate_chart: {e}")
        return None

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if "message" in data and "text" in data["message"]:
        text = data["message"]["text"].strip().upper()
        chat_id = data["message"]["chat"]["id"]

        if len(text) >= 6 and text.isalnum():
            try:
                message, signal = analyze_multi_timeframe(text)
                TELEGRAM_BOT.send_message(chat_id, message, parse_mode="Markdown")

                if signal != "NONE":
                    chart = generate_chart(text, signal)
                    if chart:
                        try:
                            TELEGRAM_BOT.send_photo(chat_id, chart)
                        except Exception as e:
                            print(f"❌ Error send_photo: {e}")

                    try:
                        markup = InlineKeyboardMarkup()
                        button = InlineKeyboardButton(
                            text=f"Buka {text} di Binance 📲",
                            url=f"https://www.binance.com/en/futures/{text}?ref=GRO_16987_24H8Y"
                        )
                        markup.add(button)
                        TELEGRAM_BOT.send_message(chat_id, "Klik tombol di bawah untuk buka di aplikasi Binance:", reply_markup=markup)
                    except Exception as e:
                        print(f"❌ Error kirim tombol: {e}")

            except Exception as e:
                TELEGRAM_BOT.send_message(chat_id, f"Error analisis: {e}")
        else:
            TELEGRAM_BOT.send_message(chat_id, "Format simbol tidak valid atau terlalu pendek.")
    return "OK"

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
