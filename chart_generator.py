import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
from io import BytesIO
from binance.client import Client
import os
import pandas as pd
import ta

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

def get_klines(symbol, interval="1h", limit=100):
    try:
        raw = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        if not raw:
            return None
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
        print(f"Error get_klines (chart): {e}")
        return None

def generate_chart(symbol, signal_type="NONE", entry_price=None):
    df = get_klines(symbol, interval="1h", limit=100)
    if df is None or df.empty:
        return None

    df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50)
    df['EMA200'] = ta.trend.ema_indicator(df['close'], window=200)

    addplot = [
        mpf.make_addplot(df['EMA50'], color='green'),
        mpf.make_addplot(df['EMA200'], color='red')
    ]

    if signal_type == "LONG" and entry_price:
        addplot.append(mpf.make_addplot([np.nan]*(len(df)-1) + [entry_price],
                                        type='scatter', markersize=100, marker='^', color='green'))
    elif signal_type == "SHORT" and entry_price:
        addplot.append(mpf.make_addplot([np.nan]*(len(df)-1) + [entry_price],
                                        type='scatter', markersize=100, marker='v', color='red'))

    try:
        fig, ax = mpf.plot(
            df, type='candle', style='yahoo', addplot=addplot,
            volume=True, returnfig=True, figsize=(8, 6),
            title=f"{symbol} - Signal Future Pro"
        )
        ax[0].text(0.02, 0.95, "Signal Future Pro", transform=ax[0].transAxes,
                   fontsize=14, fontweight='bold', color='blue', bbox=dict(facecolor='white', alpha=0.7))

        buf = BytesIO()
        fig.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"Error generate_chart: {e}")
        return None
