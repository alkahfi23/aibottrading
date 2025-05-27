from flask import Flask, request
import os
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import ta
import telebot
import ccxt
from datetime import datetime, timedelta
from binance.client import Client
from io import BytesIO

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# Fungsi analisa lengkap pair
def analyze_pair(symbol):
    df = get_klines(symbol, interval=Client.KLINE_INTERVAL_5MINUTE, limit=100)
    if df is None:
        return "Data tidak tersedia."

    # Hitung indikator teknikal
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
    current_price = round(last['close'], 2)
    
    # Support dan Resistance (dari harga terendah dan tertinggi)
    support = round(df['low'][-20:].min(), 2)
    resistance = round(df['high'][-20:].max(), 2)

    # Volume spike detection
    avg_volume = df['volume'].rolling(window=20).mean()
    volume_spike = last['volume'] > avg_volume.iloc[-1] * 1.5

    # Sinyal teknikal
    trend = "Bullish" if last['EMA20'] > last['EMA50'] else "Bearish"
    rsi_status = f"{round(last['RSI'],1)} (Overbought)" if last['RSI'] > 70 else f"{round(last['RSI'],1)} (Oversold)" if last['RSI'] < 30 else f"{round(last['RSI'],1)} (Netral)"
    macd_signal = "✅ Bullish Crossover" if last['MACD'] > last['MACD_SIGNAL'] else "❌ Bearish Crossover"
    adx_strength = round(last['ADX'],1)
    bb_status = "Breakout atas" if last['close'] > last['BB_H'] else "Breakout bawah" if last['close'] < last['BB_L'] else "Dalam band"

    # Validasi sinyal akhir
    signal = "NONE"
    if trend == "Bullish" and last['MACD'] > last['MACD_SIGNAL'] and last['RSI'] > 50:
        signal = "LONG"
    elif trend == "Bearish" and last['MACD'] < last['MACD_SIGNAL'] and last['RSI'] < 50:
        signal = "SHORT"

    # Entry & SL/TP
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

    if signal in ["LONG", "SHORT"]:
        result += f"\n📍 [Buka Binance {symbol}](https://www.binance.com/en/futures/{symbol})"

    return result.strip(), signal

# Fungsi chart
import ccxt

def get_klines(symbol, interval="5m", limit=100):
    try:
        binance = ccxt.binance()
        bars = binance.fetch_ohlcv(symbol.replace("/", ""), timeframe=interval, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df
    except Exception as e:
        print(f"Error get_klines: {e}")
        return None

def generate_chart(symbol):
    df = get_klines(symbol, interval="5m", limit=100)
    if df is None:
        return None

    df['EMA20'] = ta.trend.ema_indicator(df['close'], window=20)
    df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50)
    addplot = [
        mpf.make_addplot(df['EMA20'], color='green'),
        mpf.make_addplot(df['EMA50'], color='red')
    ]

    fig, ax = mpf.plot(
        df,
        type='candle',
        style='yahoo',
        addplot=addplot,
        volume=True,
        returnfig=True,
        figsize=(8,6),
        title=f"{symbol} - 5m"
    )

    buf = BytesIO()
    fig.savefig(buf, format="png")
    buf.seek(0)
    return buf

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if "message" in data and "text" in data["message"]:
        text = data["message"]["text"].strip().upper()
        chat_id = data["message"]["chat"]["id"]

        if len(text) >= 6:  # Asumsi ini adalah pair
            try:
                message, signal = analyze_pair(text)
                TELEGRAM_BOT.send_message(chat_id, message, parse_mode="Markdown")

                if signal != "NONE":
                    chart = generate_chart(text)
                    if chart:
                        TELEGRAM_BOT.send_photo(chat_id, chart)
            except Exception as e:
                TELEGRAM_BOT.send_message(chat_id, f"Error analisis: {e}")

    return "OK"
