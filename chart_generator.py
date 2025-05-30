import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
from io import BytesIO
from binance.client import Client
import os
import pandas as pd
import ta

# Ambil API key dari environment variable
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

def get_klines(symbol, interval="1h", limit=250):
    try:
        raw = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        if not raw:
            print("⚠️ Klines kosong.")
            return None

        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].astype(float)

        return df[numeric_cols]
    except Exception as e:
        print(f"❌ Error get_klines (chart): {e}")
        return None

def generate_chart(symbol, signal_type="NONE", entry_price=None):
    df = get_klines(symbol, interval="1h", limit=250)
    if df is None or df.empty or df.shape[0] < 200:
        print("⚠️ Data tidak cukup untuk chart (minimal 200 bar).")
        return None

    try:
        df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50, fillna=True)
        df['EMA200'] = ta.trend.ema_indicator(df['close'], window=200, fillna=True)

        addplot = [
            mpf.make_addplot(df['EMA50'], color='lime', width=1.2),
            mpf.make_addplot(df['EMA200'], color='orangered', width=1.2),
        ]

        if signal_type in ["LONG", "SHORT"] and entry_price:
            marker_symbol = '^' if signal_type == "LONG" else 'v'
            marker_color = 'green' if signal_type == "LONG" else 'red'

            # Taruh marker pada candle terakhir
            marker_array = [np.nan] * (len(df) - 1) + [df['low'].iloc[-1] if signal_type == "LONG" else df['high'].iloc[-1]]
            addplot.append(mpf.make_addplot(marker_array, type='scatter', markersize=150,
                                            marker=marker_symbol, color=marker_color))

            # Tambahkan garis horizontal di entry price
            df['entry_line'] = entry_price
            addplot.append(mpf.make_addplot(df['entry_line'], color='gray', linestyle='--', linewidth=1))

        # Plot dengan mplfinance
        fig, ax = mpf.plot(
            df,
            type='candle',
            style='charles',
            addplot=addplot,
            volume=True,
            returnfig=True,
            figsize=(10, 6),
            title=f"{symbol} | {signal_type} @ {entry_price}" if signal_type in ["LONG", "SHORT"] else f"{symbol} - Signal Future Pro",
        )

        # Watermark/info
        ax[0].text(0.02, 0.95, "Signal Future Pro", transform=ax[0].transAxes,
                   fontsize=14, fontweight='bold', color='navy',
                   bbox=dict(facecolor='white', edgecolor='blue', boxstyle='round,pad=0.5', alpha=0.7))

        # Simpan ke buffer PNG
        buf = BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return buf

    except Exception as e:
        print(f"❌ Error generate_chart: {e}")
        return None
