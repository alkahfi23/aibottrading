from flask import Flask, request
import os
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
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

def get_klines(symbol, interval=Client.KLINE_INTERVAL_5MINUTE, limit=100):
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
        print(f"Error get_klines: {e}")
        return None

def analyze_pair(symbol):
    df = get_klines(symbol)
    if df is None:
        return "Data tidak tersedia.", "NONE"

    df['EMA20'] = ta.trend.ema_indicator(df['close'], window=20)
    df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50)
    df['RSI'] = ta.momentum.rsi(df['close'], window=14)
    macd = ta.trend.MACD(df['close'])
    df['MACD'] = macd.macd()
    df['MACD_SIGNAL'] = macd.macd_signal()
    df['ADX'] = ta.trend.adx(df['high'], df['low'], df['close'], window=14)
    bb = ta.volatility.BollingerBands(df['close'])
    df['BB_H'] = bb.bollinger_hband()
    df['BB_L'] = bb.bollinger_lband()

    last = df.iloc[-1]
    current_price = last['close']
    support = df['low'][-20:].min()
    resistance = df['high'][-20:].max()

    avg_volume = df['volume'].rolling(window=20).mean()
    volume_spike = last['volume'] > avg_volume.iloc[-1] * 1.5

    trend = "Bullish" if last['EMA20'] > last['EMA50'] else "Bearish"
    rsi_status = f"{round(last['RSI'],1)} (Overbought)" if last['RSI'] > 70 else f"{round(last['RSI'],1)} (Oversold)" if last['RSI'] < 30 else f"{round(last['RSI'],1)} (Netral)"
    macd_signal = "✅ Bullish Crossover" if last['MACD'] > last['MACD_SIGNAL'] else "❌ Bearish Crossover"
    adx_strength = round(last['ADX'],1)
    bb_status = "Breakout atas" if last['close'] > last['BB_H'] else "Breakout bawah" if last['close'] < last['BB_L'] else "Dalam band"

    signal = "NONE"
    if trend == "Bullish" and last['MACD'] > last['MACD_SIGNAL'] and last['RSI'] > 50:
        signal = "LONG"
    elif trend == "Bearish" and last['MACD'] < last['MACD_SIGNAL'] and last['RSI'] < 50:
        signal = "SHORT"

    if signal == "LONG":
        entry = current_price
        sl = support
        tp = resistance
    elif signal == "SHORT":
        entry = current_price
        sl = resistance
        tp = support
    else:
        entry = sl = tp = "-"

    result = f"""
📊 Pair: {symbol}
💰 Harga Terkini: ${current_price}
📈 Trend: {trend}
📍 Support: ${support}
📍 Resistance: ${resistance}
📉 Volume Spike: {'Aktif 🚨' if volume_spike else 'Tidak'}
📌 RSI: {rsi_status}
📌 MACD: {macd_signal}
📌 ADX: {adx_strength}
📌 EMA20 vs EMA50: {'Golden Cross' if trend == 'Bullish' else 'Death Cross'}
📊 Bollinger Bands: {bb_status}

📤 Sinyal Validasi Akhir: {'✅ ' + signal if signal != 'NONE' else '⛔ Tidak ada sinyal valid'}
🎯 Saran Entry: {entry}
🛡️ Stop Loss: {sl}
🎯 Take Profit: {tp}
"""
    return result.strip(), signal

def generate_chart(symbol, signal=None):
    df = get_klines(symbol)
    if df is None:
        return None

    df['EMA20'] = ta.trend.ema_indicator(df['close'], window=20)
    df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50)

    addplot = [
        mpf.make_addplot(df['EMA20'], color='green'),
        mpf.make_addplot(df['EMA50'], color='red')
    ]

    last_idx = df.index[-1]
    last_close = df['close'].iloc[-1]
    signal_annotation = ""
    if signal == "LONG":
        signal_annotation = '📈 BUY SIGNAL'
    elif signal == "SHORT":
        signal_annotation = '📉 SELL SIGNAL'

    fig, axlist = mpf.plot(
        df,
        type='candle',
        style='yahoo',
        addplot=addplot,
        volume=True,
        returnfig=True,
        figsize=(8,6),
        title=f"{symbol} - 5m (Signal Future Pro)"
    )

    ax = axlist[0]
    if signal_annotation:
        ax.annotate(
            signal_annotation,
            xy=(last_idx, last_close),
            xytext=(last_idx, last_close * 1.01 if signal == "LONG" else last_close * 0.99),
            fontsize=12,
            color='blue' if signal == "LONG" else 'red',
            arrowprops=dict(facecolor='green' if signal == "LONG" else 'red', arrowstyle="->")
        )

    buf = BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if "message" in data and "text" in data["message"]:
        text = data["message"]["text"].strip().upper()
        chat_id = data["message"]["chat"]["id"]

        if len(text) >= 6:
            try:
                message, signal = analyze_pair(text)
                TELEGRAM_BOT.send_message(chat_id, message, parse_mode="Markdown")

                if signal != "NONE":
                    chart = generate_chart(text, signal=signal)
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
    return "OK"

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
