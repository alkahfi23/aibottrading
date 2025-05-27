import os
import io
import json
import numpy as np
import pandas as pd
import requests
import ta
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from flask import Flask, request
import matplotlib.pyplot as plt
from datetime import datetime

app = Flask(__name__)

TOKEN = os.getenv("BOT_TOKEN")  # Set di Railway sebagai variabel lingkungan
bot = Bot(token=TOKEN)

# === Utility Functions ===
def fetch_klines(symbol: str, interval='1m', limit=200):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol.upper()}&interval={interval}&limit={limit}"
    data = requests.get(url).json()
    df = pd.DataFrame(data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df

def generate_fibonacci_levels(df):
    max_price = df['high'][-50:].max()
    min_price = df['low'][-50:].min()
    diff = max_price - min_price
    levels = {
        '0.0': max_price,
        '0.236': max_price - 0.236 * diff,
        '0.382': max_price - 0.382 * diff,
        '0.5': max_price - 0.5 * diff,
        '0.618': max_price - 0.618 * diff,
        '0.786': max_price - 0.786 * diff,
        '1.0': min_price,
    }
    return levels

def analyze_signal(df):
    df['ema'] = ta.trend.ema_indicator(df['close'], window=20)
    df['macd'] = ta.trend.macd_diff(df['close'])
    df['rsi'] = ta.momentum.rsi(df['close'])
    df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'])

    last = df.iloc[-1]
    if (
        last['close'] > last['ema'] and
        last['macd'] > 0 and
        last['rsi'] > 50 and
        last['adx'] > 20
    ):
        return "LONG"
    elif (
        last['close'] < last['ema'] and
        last['macd'] < 0 and
        last['rsi'] < 50 and
        last['adx'] > 20
    ):
        return "SHORT"
    return "NONE"

def estimate_direction(df):
    df['return'] = df['close'].pct_change()
    mean_ret = df['return'].mean()
    return "UP" if mean_ret > 0 else "DOWN"

def find_support_resistance(df):
    support = df['low'][-50:].min()
    resistance = df['high'][-50:].max()
    return support, resistance

def volume_spike(df):
    avg_vol = df['volume'][:-1].mean()
    last_vol = df['volume'].iloc[-1]
    return last_vol > avg_vol * 1.5

def plot_chart(df, symbol):
    levels = generate_fibonacci_levels(df)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df.index, df['close'], label='Close')
    for label, level in levels.items():
        ax.axhline(level, linestyle='--', alpha=0.5, label=f"Fib {label}")
    ax.set_title(f"{symbol} Chart with Fibonacci")
    ax.legend()
    ax.grid(True)
    plt.xticks(rotation=45)
    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    return buf

# === Route Handler ===
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json()
    if "message" not in data:
        return "ok"
    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    cmd = text.upper().split()

    if len(cmd) >= 2:
        command = cmd[0]
        symbol = cmd[1].upper()

        try:
            df = fetch_klines(symbol)

            if command == "CHART":
                chart = plot_chart(df, symbol)
                bot.send_photo(chat_id, photo=chart)

            elif command == "PAIR":
                signal = analyze_signal(df)
                text = f"🔍 *Signal for {symbol}*\nStatus: *{signal}*"

                if signal in ["LONG", "SHORT"]:
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔗 Open in Binance Futures", url=f"https://www.binance.com/en/futures/{symbol}")]
                    ])
                    bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN)

            elif command == "PAIRVOL":
                spike = volume_spike(df)
                msg = f"📈 Volume Spike: {'Yes 🚨' if spike else 'No'}"
                bot.send_message(chat_id, msg)

            elif command == "PAIREST":
                direction = estimate_direction(df)
                bot.send_message(chat_id, f"📊 Estimated Direction: *{direction}*", parse_mode=ParseMode.MARKDOWN)

            elif command == "PAIRSSUP":
                support, resistance = find_support_resistance(df)
                msg = f"📉 Support: `{support:.2f}`\n📈 Resistance: `{resistance:.2f}`"
                bot.send_message(chat_id, msg, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: {str(e)}")

    return "ok"

# === App Start ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
