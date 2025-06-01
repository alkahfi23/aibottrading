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

# === Konfigurasi ===
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
bot = Bot(token=TELEGRAM_TOKEN)

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === Ambil Data ===
def get_klines(symbol, interval="1m", limit=250):
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

# === Chart Timeframe ===
def draw_chart(ax, df, timeframe):
    df['EMA50'] = ta.trend.EMAIndicator(df['close'], 50).ema_indicator()
    df['EMA200'] = ta.trend.EMAIndicator(df['close'], 200).ema_indicator()
    df['RSI'] = ta.momentum.RSIIndicator(df['close']).rsi()
    macd = ta.trend.macd_diff(df['close'])
    st = calculate_supertrend(df)

    # Support & Resistance
    support_idx = argrelextrema(df['low'].values, np.less_equal, order=10)[0]
    resistance_idx = argrelextrema(df['high'].values, np.greater_equal, order=10)[0]
    support = df['low'].iloc[support_idx].tail(3)
    resistance = df['high'].iloc[resistance_idx].tail(3)

    ax.plot(df.index, df['close'], label='Close', color='black', linewidth=1)
    ax.plot(df.index, df['EMA50'], label='EMA50', color='lime')
    ax.plot(df.index, df['EMA200'], label='EMA200', color='orange')
    ax.fill_between(df.index, st['lowerband'], st['upperband'], where=st['supertrend'], color='green', alpha=0.1)
    ax.fill_between(df.index, st['lowerband'], st['upperband'], where=~st['supertrend'], color='red', alpha=0.1)

    for s in support:
        ax.axhspan(s*0.995, s*1.005, color='green', alpha=0.15)
        ax.axhline(s, color='green', linestyle='--', linewidth=0.7)
    for r in resistance:
        ax.axhspan(r*0.995, r*1.005, color='red', alpha=0.15)
        ax.axhline(r, color='red', linestyle='--', linewidth=0.7)

    last_close = df['close'].iloc[-1]
    if any(last_close > resistance):
        ax.annotate("Breakout ↑", xy=(df.index[-1], last_close), color='green',
                    xytext=(-60, 10), textcoords='offset points',
                    arrowprops=dict(arrowstyle="->", color='green'))
    elif any(last_close < support):
        ax.annotate("Breakdown ↓", xy=(df.index[-1], last_close), color='red',
                    xytext=(-60, -20), textcoords='offset points',
                    arrowprops=dict(arrowstyle="->", color='red'))

    ax.set_title(f"{timeframe} Chart", fontsize=10)
    ax.legend(fontsize=6)
    ax.tick_params(axis='x', labelsize=6)
    ax.tick_params(axis='y', labelsize=6)

# === Generate Chart ===
def generate_chart(symbol='BTCUSDT'):
    timeframes = ['1m', '5m', '15m', '1h']
    fig, axs = plt.subplots(2, 2, figsize=(15, 10), sharex=False)
    axs = axs.flatten()

    try:
        for i, tf in enumerate(timeframes):
            try:
                df = get_klines(symbol, interval=tf, limit=250)
                draw_chart(axs[i], df, tf)
            except Exception as e:
                logging.warning(f"❌ Gagal memuat timeframe {tf}: {e}")
                axs[i].set_title(f"{tf} - Error")

        fig.text(0.5, 0.02, 'Signal Future Pro', fontsize=20,
                 color='navy', ha='center', va='center', alpha=0.25, weight='bold')
        plt.suptitle(f'{symbol} Multi Timeframe', fontsize=16, weight='bold')
        plt.tight_layout(rect=[0, 0.03, 1, 0.97])

        buf = BytesIO()
        plt.savefig(buf, format='png')
        plt.close()
        buf.seek(0)
        return buf

    except Exception as e:
        logging.error(f"❌ Gagal generate chart {symbol}: {e}")
        return None
