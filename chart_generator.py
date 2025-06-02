import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from datetime import datetime
from binance.client import Client
from scipy.signal import argrelextrema
import ta
import logging
from telegram import Bot
import mplfinance as mpf
from ta.momentum import RSIIndicator
from ta.trend import MACD
from mplfinance.original_flavor import candlestick_ohlc
import matplotlib.dates as mdates

# === Konfigurasi ===
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
bot = Bot(token=TELEGRAM_TOKEN)

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === Ambil Data dari Binance ===
def get_klines(symbol, interval="1m", limit=500):
    raw = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(raw, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df

# === Supertrend ===
def calculate_supertrend(df, period=10, multiplier=3):
    hl2 = (df['high'] + df['low']) / 2
    atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=period).average_true_range()
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)
    supertrend = [True] * len(df)

    for i in range(1, len(df)):
        if df['close'].iloc[i] > upperband.iloc[i - 1]:
            supertrend[i] = True
        elif df['close'].iloc[i] < lowerband.iloc[i - 1]:
            supertrend[i] = False
        else:
            supertrend[i] = supertrend[i - 1]
            if supertrend[i] and lowerband.iloc[i] < lowerband.iloc[i - 1]:
                lowerband.iloc[i] = lowerband.iloc[i - 1]
            if not supertrend[i] and upperband.iloc[i] > upperband.iloc[i - 1]:
                upperband.iloc[i] = upperband.iloc[i - 1]

    return pd.DataFrame({
        'supertrend': supertrend,
        'upperband': upperband,
        'lowerband': lowerband
    }, index=df.index)

# === Multi Timeframe Chart ===
def draw_chart_by_timeframe(symbol='BTCUSDT', tf='1m'):
    df = get_klines(symbol, interval=tf)
    df['EMA50'] = ta.trend.EMAIndicator(df['close'], 50).ema_indicator()
    df['EMA200'] = ta.trend.EMAIndicator(df['close'], 200).ema_indicator()

    boll = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
    df['BB_upper'] = boll.bollinger_hband()
    df['BB_middle'] = boll.bollinger_mavg()
    df['BB_lower'] = boll.bollinger_lband()

    df['RSI'] = RSIIndicator(df['close'], window=14).rsi()
    macd = MACD(df['close'], window_slow=26, window_fast=12, window_sign=9)
    df['MACD'] = macd.macd()
    df['MACD_signal'] = macd.macd_signal()

    st = calculate_supertrend(df)
    df['Volume_MA20'] = df['volume'].rolling(window=20).mean()

    df_ohlc = df[['open', 'high', 'low', 'close']].copy()
    df_ohlc['Date'] = df_ohlc.index.map(mdates.date2num)
    ohlc = df_ohlc[['Date', 'open', 'high', 'low', 'close']]

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 9), sharex=True,
                                        gridspec_kw={'height_ratios': [3, 1.5, 1]})

    offset_map = {
        '1m': pd.Timedelta(minutes=2),
        '5m': pd.Timedelta(minutes=10),
        '15m': pd.Timedelta(minutes=20),
        '1h': pd.Timedelta(hours=1),
        '4h': pd.Timedelta(hours=2),
        '1d': pd.Timedelta(days=1),
    }
    x_offset = offset_map.get(tf, pd.Timedelta(minutes=10))

    # === Candlestick
    candlestick_ohlc(ax1, ohlc.values, width=0.0005, colorup='g', colordown='r', alpha=0.8)
    ax1.plot(df.index, df['EMA50'], color='lime', label='EMA50')
    ax1.plot(df.index, df['EMA200'], color='orange', label='EMA200')
    ax1.plot(df.index, df['BB_upper'], color='blue', linestyle='--', linewidth=0.5)
    ax1.plot(df.index, df['BB_middle'], color='blue', linewidth=0.5)
    ax1.plot(df.index, df['BB_lower'], color='blue', linestyle='--', linewidth=0.5)

    for j in range(1, len(df)):
        color = 'green' if st['supertrend'].iloc[j] else 'red'
        ax1.axvspan(df.index[j-1], df.index[j], color=color, alpha=0.03)

    # === Support & Resistance
    support_idx = argrelextrema(df['low'].values, np.less_equal, order=10)[0]
    resistance_idx = argrelextrema(df['high'].values, np.greater_equal, order=10)[0]
    support = df['low'].iloc[support_idx].tail(3)
    resistance = df['high'].iloc[resistance_idx].tail(3)

    x_pos = df.index[-1]

    for s in support:
        ax1.axhline(s, color='green', linestyle='--', linewidth=0.5)
        ax1.text(x_pos + x_offset, s, f'{s:.2f}', va='center', ha='left',
                 fontsize=7, color='green',
                 bbox=dict(facecolor='white', alpha=0.5, edgecolor='none'))

    for r in resistance:
        ax1.axhline(r, color='red', linestyle='--', linewidth=0.5)
        ax1.text(x_pos + x_offset, r, f'{r:.2f}', va='center', ha='left',
                 fontsize=7, color='red',
                 bbox=dict(facecolor='white', alpha=0.5, edgecolor='none'))

    # === Last Price & Breaks
    last_price = df['close'].iloc[-1]
    ax1.axhline(last_price, color='black', linestyle='--', linewidth=0.6)
    ax1.text(x_pos + x_offset, last_price, f'{last_price:.2f}',
             va='center', ha='left', fontsize=8, color='black',
             bbox=dict(facecolor='white', edgecolor='black', boxstyle='round,pad=0.2', alpha=0.7))

    if not support.empty and last_price < support.min():
        ax1.annotate("⬇️ Breakdown", xy=(x_pos, last_price),
                     xytext=(x_pos, last_price * 1.01),
                     arrowprops=dict(arrowstyle="->", color='red'),
                     color='red', fontsize=9, ha='center')
    if not resistance.empty and last_price > resistance.max():
        ax1.annotate("⬆️ Breakout", xy=(x_pos, last_price),
                     xytext=(x_pos, last_price * 0.99),
                     arrowprops=dict(arrowstyle="->", color='green'),
                     color='green', fontsize=9, ha='center')

    ax1.set_title(f"{symbol} - {tf.upper()} Chart")
    ax1.xaxis_date()
    ax1.legend(fontsize=6)
    ax1.grid(True)

    # === RSI & MACD
    ax2.plot(df.index, df['RSI'], label='RSI', color='purple')
    ax2.axhline(70, color='red', linestyle='--', linewidth=0.5)
    ax2.axhline(30, color='green', linestyle='--', linewidth=0.5)

    ax2b = ax2.twinx()
    ax2b.plot(df.index, df['MACD'], label='MACD', color='black')
    ax2b.plot(df.index, df['MACD_signal'], label='Signal', color='orange', linestyle='--')
    ax2b.fill_between(df.index, df['MACD'] - df['MACD_signal'], 0,
                      where=(df['MACD'] > df['MACD_signal']), alpha=0.2, color='green')
    ax2b.fill_between(df.index, df['MACD'] - df['MACD_signal'], 0,
                      where=(df['MACD'] < df['MACD_signal']), alpha=0.2, color='red')
    ax2.set_title("RSI & MACD")
    ax2.legend(loc='upper left', fontsize=6)
    ax2b.legend(loc='upper right', fontsize=6)
    ax2.grid(True)

    # === Volume with MA
    width_map = {
        '1m': 0.0005,
        '5m': 0.002,
        '15m': 0.005,
        '1h': 0.01,
        '4h': 0.02,
        '1d': 0.05
    }
    bar_width = width_map.get(tf, 0.002)
    colors = ['green' if c >= o else 'red' for c, o in zip(df['close'], df['open'])]

    ax3.bar(df.index, df['volume'], color=colors, width=bar_width, alpha=0.4, label='Volume')
    ax3.plot(df.index, df['Volume_MA20'], color='blue', linewidth=0.8, label='Volume MA20')
    ax3.set_title("Volume")
    ax3.set_ylabel("Volume", fontsize=8)
    ax3.legend(fontsize=6)
    ax3.grid(True)

    # === Watermark
    fig.text(0.5, 0.5, "Signal Future Pro", fontsize=40, color='gray',
             ha='center', va='center', alpha=0.1, rotation=30)

    plt.tight_layout(h_pad=1.5)
    buf = BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    return buf

def send_all_timeframes(symbol='BTCUSDT'):
    timeframes = ['1m', '5m', '15m', '1h']
    for tf in timeframes:
        try:
            chart = draw_chart_by_timeframe(symbol, tf)
            caption = f"📊 {symbol} - {tf.upper()} Multi-Indicator Chart"
            bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=chart, caption=caption)
        except Exception as e:
            logging.warning(f"Gagal kirim chart {tf}: {e}")
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"❌ Gagal kirim chart {symbol} - {tf}")
