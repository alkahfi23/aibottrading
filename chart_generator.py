import io
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from binance.client import Client
import pandas as pd
import os

# Load API untuk ambil data chart
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

def get_ohlc(symbol, interval="1m", limit=100):
    try:
        raw = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(raw, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df[['open', 'high', 'low', 'close']]
        df = df.astype(float)
        return df
    except Exception as e:
        print(f"⚠️ Error get_ohlc: {e}")
        return None

def generate_chart(symbol, signal, entry_price):
    df = get_ohlc(symbol, "1m", 100)
    if df is None or df.empty:
        return None

    fig, ax = plt.subplots(figsize=(10, 5))

    # Candlestick plot
    for idx in range(len(df)):
        o, h, l, c = df.iloc[idx]
        color = 'green' if c >= o else 'red'
        ax.plot([df.index[idx], df.index[idx]], [l, h], color='black')
        ax.plot([df.index[idx], df.index[idx]], [o, c], linewidth=6, color=color)

    # Garis entry
    if entry_price:
        label = f"Entry ({signal})"
        ax.axhline(entry_price, color='blue', linestyle='--', label=label)

    # Format chart
    ax.set_title(f"{symbol} Chart - Sinyal {signal}")
    ax.set_ylabel("Harga")
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.legend()
    ax.grid(True)

    # Save chart to buffer
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)

    return buf
