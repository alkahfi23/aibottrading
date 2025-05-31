import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import mplfinance as mpf
import ta  # Technical Analysis library
from io import BytesIO


def get_klines(symbol, interval="5m", limit=100):
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
        print(f"Error get_klines ({interval}): {e}")
        return None

def generate_chart(symbol: str, signal_type: str = "NONE", entry_price: float = None) -> BytesIO:
    df = get_klines(symbol, interval="1h", limit=250)
    if df is None or df.empty or df.shape[0] < 200:
        print("⚠️ Data tidak cukup untuk membuat chart (minimal 200 bar).")
        return None

    try:
        # === Indikator: EMA, RSI, Bollinger Bands ===
        df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50, fillna=True)
        df['EMA200'] = ta.trend.ema_indicator(df['close'], window=200, fillna=True)
        df['RSI'] = ta.momentum.RSIIndicator(df['close'], window=14, fillna=True).rsi()
        bb = ta.volatility.BollingerBands(close=df['close'], window=20, window_dev=2, fillna=True)
        df['BB_upper'] = bb.bollinger_hband()
        df['BB_lower'] = bb.bollinger_lband()

        addplot = [
            mpf.make_addplot(df['EMA50'], color='lime', width=1.2),
            mpf.make_addplot(df['EMA200'], color='orangered', width=1.2),
            mpf.make_addplot(df['BB_upper'], color='skyblue', linestyle='--', width=1),
            mpf.make_addplot(df['BB_lower'], color='skyblue', linestyle='--', width=1),
        ]

        # === Tambahkan sinyal dan garis entry jika ada ===
        if signal_type in ["LONG", "SHORT"] and entry_price is not None:
            df['entry_line'] = entry_price

            # Posisi marker disesuaikan sedikit agar tidak menutupi candle
            last_index = len(df) - 1
            marker_array = [np.nan] * last_index

            if signal_type == "LONG":
                marker_val = df['low'].iloc[-1] * 0.995  # Sedikit di bawah candle
                marker_color = 'green'
                marker_symbol = '^'
            else:  # SHORT
                marker_val = df['high'].iloc[-1] * 1.005  # Sedikit di atas candle
                marker_color = 'red'
                marker_symbol = 'v'

            marker_array.append(marker_val)

            addplot += [
                mpf.make_addplot(marker_array, type='scatter', markersize=120, marker=marker_symbol, color=marker_color),
                mpf.make_addplot(df['entry_line'], color='gray', linestyle='--', width=1)
            ]

        # === Tambahkan RSI panel ===
        addplot += [
            mpf.make_addplot(df['RSI'], panel=1, color='blue'),
            mpf.make_addplot([70]*len(df), panel=1, color='red', linestyle='--'),
            mpf.make_addplot([30]*len(df), panel=1, color='green', linestyle='--'),
        ]

        # === Plot Chart ===
        fig, axlist = mpf.plot(
            df,
            type='candle',
            style='charles',
            addplot=addplot,
            volume=True,
            returnfig=True,
            figsize=(10, 8),
            title=f"{symbol} | {signal_type} @ {entry_price}" if signal_type in ["LONG", "SHORT"] else f"{symbol} - Signal Chart",
            panel_ratios=(3, 1),  # Chart utama : RSI
        )

        # === Watermark ===
        axlist[0].text(0.02, 0.95, "Signal Future Pro", transform=axlist[0].transAxes,
                       fontsize=14, fontweight='bold', color='navy',
                       bbox=dict(facecolor='white', edgecolor='blue', boxstyle='round,pad=0.5', alpha=0.7))

        # === Simpan ke buffer PNG ===
        buf = BytesIO()
        fig.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return buf

    except Exception as e:
        print(f"❌ Error generate_chart: {e}")
        return None
