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
        if df['close'][i] > upperband[i - 1]:
            supertrend[i] = True
        elif df['close'][i] < lowerband[i - 1]:
            supertrend[i] = False
        else:
            supertrend[i] = supertrend[i - 1]
            if supertrend[i] and lowerband[i] < lowerband[i - 1]:
                lowerband[i] = lowerband[i - 1]
            if not supertrend[i] and upperband[i] > upperband[i - 1]:
                upperband[i] = upperband[i - 1]

    return pd.DataFrame({
        'supertrend': supertrend,
        'upperband': upperband,
        'lowerband': lowerband
    }, index=df.index)

# === Multi Timeframe Chart ==
# Update fungsi draw_multi_timeframe
def draw_multi_timeframe(symbol='BTCUSDT'):
    timeframes = ['1m', '5m', '15m', '1h']
    fig, axs = plt.subplots(4, 2, figsize=(18, 14))
    axs = axs.reshape(4, 2)

    for i, tf in enumerate(timeframes):
        try:
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

            df_ohlc = df[['open', 'high', 'low', 'close']].copy()
            df_ohlc['Date'] = df_ohlc.index.map(mdates.date2num)
            ohlc = df_ohlc[['Date', 'open', 'high', 'low', 'close']]

            price_ax = axs[i][0]
            indi_ax = axs[i][1]

            # === Candlestick chart
            candlestick_ohlc(price_ax, ohlc.values, width=0.0005, colorup='g', colordown='r', alpha=0.8)

            # Tambahkan EMA dan BB
            price_ax.plot(df.index, df['EMA50'], color='lime', label='EMA50')
            price_ax.plot(df.index, df['EMA200'], color='orange', label='EMA200')
            price_ax.plot(df.index, df['BB_upper'], color='blue', linestyle='--', linewidth=0.5)
            price_ax.plot(df.index, df['BB_middle'], color='blue', linewidth=0.5)
            price_ax.plot(df.index, df['BB_lower'], color='blue', linestyle='--', linewidth=0.5)

            # Supertrend shading
            for j in range(1, len(df)):
                color = 'green' if st['supertrend'][j] else 'red'
                price_ax.axvspan(df.index[j-1], df.index[j], color=color, alpha=0.03)

            # Support & Resistance
            support_idx = argrelextrema(df['low'].values, np.less_equal, order=10)[0]
            resistance_idx = argrelextrema(df['high'].values, np.greater_equal, order=10)[0]
            support = df['low'].iloc[support_idx].tail(3)
            resistance = df['high'].iloc[resistance_idx].tail(3)

            for s in support:
                price_ax.axhline(s, color='green', linestyle='--', linewidth=0.5)
            for r in resistance:
                price_ax.axhline(r, color='red', linestyle='--', linewidth=0.5)

            price_ax.set_title(f"{symbol} - {tf}", fontsize=9)
            price_ax.xaxis_date()
            price_ax.tick_params(axis='x', labelrotation=15, labelsize=6)

            # === RSI & MACD
            indi_ax.plot(df.index, df['RSI'], label='RSI', color='purple')
            indi_ax.axhline(70, color='red', linestyle='--', linewidth=0.5)
            indi_ax.axhline(30, color='green', linestyle='--', linewidth=0.5)
            indi_ax2 = indi_ax.twinx()
            indi_ax2.plot(df.index, df['MACD'], label='MACD', color='black')
            indi_ax2.plot(df.index, df['MACD_signal'], label='Signal', color='orange', linestyle='--')
            indi_ax2.fill_between(df.index, df['MACD'] - df['MACD_signal'], 0,
                                  where=(df['MACD'] > df['MACD_signal']),
                                  alpha=0.2, color='green')
            indi_ax2.fill_between(df.index, df['MACD'] - df['MACD_signal'], 0,
                                  where=(df['MACD'] < df['MACD_signal']),
                                  alpha=0.2, color='red')

            indi_ax.set_title(f"{tf} - RSI & MACD", fontsize=8)
            indi_ax.tick_params(axis='x', labelrotation=15, labelsize=6)
        except Exception as e:
            axs[i][0].set_title(f"{tf} - Error: {e}")
            logging.warning(f"Gagal memuat timeframe {tf}: {e}")

    fig.text(0.5, 0.01, 'Signal Future Pro', fontsize=24,
             color='navy', ha='center', va='center', alpha=0.2, weight='bold')
    plt.suptitle(f"{symbol} Multi-Timeframe + RSI & MACD", fontsize=16, weight='bold')
    plt.tight_layout(rect=[0, 0.03, 1, 0.96])

    buf = BytesIO()
    plt.savefig(buf, format='png')
    plt.close()
    buf.seek(0)
    return buf
