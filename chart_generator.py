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


# === Multi Timeframe Chart ==
# Update fungsi draw_multi_timeframe
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

    df_ohlc = df[['open', 'high', 'low', 'close']].copy()
    df_ohlc['Date'] = df_ohlc.index.map(mdates.date2num)
    ohlc = df_ohlc[['Date', 'open', 'high', 'low', 'close']]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                   gridspec_kw={'height_ratios': [3, 1]})

    # === Candlestick chart
    candlestick_ohlc(ax1, ohlc.values, width=0.0005, colorup='g', colordown='r', alpha=0.8)
    ax1.plot(df.index, df['EMA50'], color='lime', label='EMA50')
    ax1.plot(df.index, df['EMA200'], color='orange', label='EMA200')
    ax1.plot(df.index, df['BB_upper'], color='blue', linestyle='--', linewidth=0.5)
    ax1.plot(df.index, df['BB_middle'], color='blue', linewidth=0.5)
    ax1.plot(df.index, df['BB_lower'], color='blue', linestyle='--', linewidth=0.5)

    for j in range(1, len(df)):
        color = 'green' if st['supertrend'].iloc[j] else 'red'
        ax1.axvspan(df.index[j-1], df.index[j], color=color, alpha=0.03)

     # Support & Resistance dengan label harga tanpa menutupi candle
    support_idx = argrelextrema(df['low'].values, np.less_equal, order=10)[0]
    resistance_idx = argrelextrema(df['high'].values, np.greater_equal, order=10)[0]

    support = df['low'].iloc[support_idx].tail(3)
    resistance = df['high'].iloc[resistance_idx].tail(3)

    x_pos = df.index[-1]  # ambil posisi x paling kanan
    x_offset = pd.Timedelta(minutes=5)  # geser label sedikit ke kanan (tergantung tf)
    # Tambahkan garis & label support
    for s in support:
        ax1.axhline(s, color='green', linestyle='--', linewidth=0.5)
        ax1.text(x_pos + x_offset, s, f'{s:.2f}', va='center', ha='left',
             fontsize=7, color='green',
             bbox=dict(facecolor='white', alpha=0.5, edgecolor='none'))

    # Tambahkan garis & label resistance
    for r in resistance:
        ax1.axhline(r, color='red', linestyle='--', linewidth=0.5)
        ax1.text(x_pos + x_offset, r, f'{r:.2f}', va='center', ha='left',
             fontsize=7, color='red',
             bbox=dict(facecolor='white', alpha=0.5, edgecolor='none'))

    # === Breakout / Breakdown Detection
    last_close = df['close'].iloc[-1]
    last_time = df.index[-1]

    if not support.empty and last_close < support.min():
        ax1.annotate("⬇️ Breakdown", xy=(last_time, last_close),
                     xytext=(last_time, last_close * 1.01),
                     arrowprops=dict(arrowstyle="->", color='red'),
                     color='red', fontsize=9, ha='center')

    if not resistance.empty and last_close > resistance.max():
        ax1.annotate("⬆️ Breakout", xy=(last_time, last_close),
                     xytext=(last_time, last_close * 0.99),
                     arrowprops=dict(arrowstyle="->", color='green'),
                     color='green', fontsize=9, ha='center')

    ax1.set_title(f"{symbol} - {tf} Chart")
    ax1.xaxis_date()
    ax1.legend(fontsize=6)
    ax1.grid(True)

    # === RSI & MACD subplot
    ax2.plot(df.index, df['RSI'], label='RSI', color='purple')
    ax2.axhline(70, color='red', linestyle='--', linewidth=0.5)
    ax2.axhline(30, color='green', linestyle='--', linewidth=0.5)

    ax3 = ax2.twinx()
    ax3.plot(df.index, df['MACD'], label='MACD', color='black')
    ax3.plot(df.index, df['MACD_signal'], label='Signal', color='orange', linestyle='--')
    ax3.fill_between(df.index, df['MACD'] - df['MACD_signal'], 0,
                     where=(df['MACD'] > df['MACD_signal']),
                     alpha=0.2, color='green')
    ax3.fill_between(df.index, df['MACD'] - df['MACD_signal'], 0,
                     where=(df['MACD'] < df['MACD_signal']),
                     alpha=0.2, color='red')

    ax2.set_title("RSI & MACD")
    ax2.legend(loc='upper left', fontsize=6)
    ax3.legend(loc='upper right', fontsize=6)
    ax2.grid(True)

    # === Watermark
    fig.text(0.5, 0.5, "Signal Future Pro", fontsize=40, color='gray',
             ha='center', va='center', alpha=0.1, rotation=30)

    plt.tight_layout()
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

