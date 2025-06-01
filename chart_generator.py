import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
from io import BytesIO
from scipy.signal import argrelextrema
from binance.client import Client
import os
import pandas as pd
import ta

# === Init Binance Client ===
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# === Ambil Data Klines ===
def get_klines(symbol: str, interval: str, limit: int = 250) -> pd.DataFrame:
    try:
        raw = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        float_cols = ['open', 'high', 'low', 'close', 'volume']
        df[float_cols] = df[float_cols].astype(float)
        return df[float_cols]
    except Exception as e:
        print(f"❌ Error get_klines: {e}")
        return None

# === Buat Chart per Timeframe ===
def prepare_chart(df: pd.DataFrame, symbol: str, tf: str, entry_price=None, signal_type=None):
    df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50, fillna=True)
    df['EMA200'] = ta.trend.ema_indicator(df['close'], window=200, fillna=True)
    bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2, fillna=True)
    df['BB_upper'] = bb.bollinger_hband()
    df['BB_lower'] = bb.bollinger_lband()

    addplot = [
        mpf.make_addplot(df['EMA50'], color='lime', width=1.2),
        mpf.make_addplot(df['EMA200'], color='orangered', width=1.2),
        mpf.make_addplot(df['BB_upper'], color='skyblue', linestyle='--', width=1),
        mpf.make_addplot(df['BB_lower'], color='skyblue', linestyle='--', width=1),
    ]

    if signal_type and entry_price:
        df['entry_line'] = entry_price
        last_index = len(df) - 1
        marker_array = [np.nan] * last_index
        marker_val = df['low'].iloc[-1] * 0.995 if signal_type == "LONG" else df['high'].iloc[-1] * 1.005
        marker_color = 'green' if signal_type == "LONG" else 'red'
        marker_symbol = '^' if signal_type == "LONG" else 'v'
        marker_array.append(marker_val)

        addplot += [
            mpf.make_addplot(marker_array, type='scatter', markersize=100, marker=marker_symbol, color=marker_color),
            mpf.make_addplot(df['entry_line'], color='gray', linestyle='--', width=1)
        ]

    fig, _ = mpf.plot(
        df,
        type='candle',
        style='charles',
        addplot=addplot,
        returnfig=True,
        title=f"{symbol} | TF: {tf}",
        figsize=(6, 4),
        tight_layout=True,
    )
    return fig

# === Generate Multi-Timeframe Chart ===
def generate_multitimeframe_chart(symbol: str, entry_price=None, signal_type=None) -> BytesIO:
    timeframes = {"1m": "1 Minute", "5m": "5 Minute", "15m": "15 Minute", "1h": "1 Hour"}
    figs = []

    for tf in timeframes:
        df = get_klines(symbol, interval=tf, limit=250)
        if df is None or df.shape[0] < 200:
            print(f"⚠️ Data {tf} tidak cukup.")
            figs.append(None)
            continue
        fig = prepare_chart(df, symbol, tf, entry_price, signal_type)
        figs.append(fig)

    # Gabung ke satu canvas (2x2)
    final_fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    plt.subplots_adjust(hspace=0.3, wspace=0.2)

    for i, fig in enumerate(figs):
        if fig:
            buf = BytesIO()
            fig.savefig(buf, format='png')
            buf.seek(0)
            img = plt.imread(buf)
            ax = axes[i // 2, i % 2]
            ax.imshow(img)
            ax.axis('off')
            plt.close(fig)
        else:
            axes[i // 2, i % 2].text(0.5, 0.5, 'No Data', ha='center', va='center')
            axes[i // 2, i % 2].axis('off')

    final_fig.suptitle(f"{symbol} - Multi-Timeframe Chart", fontsize=16, fontweight='bold')
    buf = BytesIO()
    final_fig.savefig(buf, format='png', bbox_inches='tight')
    plt.close(final_fig)
    buf.seek(0)
    return buf
