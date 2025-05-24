import os, time, datetime
import pandas as pd
import requests
from datetime import datetime, timezone
from ta.trend import EMAIndicator, ADXIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange

from trade import execute_trade, position_exists, close_opposite_position
from notifikasi import kirim_notifikasi_order, kirim_notifikasi_penutupan
from utils import get_futures_balance, set_leverage, get_dynamic_leverage, get_dynamic_risk_pct

BASE_URL = "https://api.binance.com"
SYMBOLS = ["BTCUSDT"]
INTERVAL = "1m"
LIMIT = 100

def get_klines(symbol, interval, limit):
    url = f"{BASE_URL}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    res = requests.get(url)
    data = res.json()
    df = pd.DataFrame(data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
    ])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df

def calculate_indicators(df):
    df['ema'] = EMAIndicator(df['close'], window=20).ema_indicator()
    df['rsi'] = RSIIndicator(df['close'], window=14).rsi()
    df['adx'] = ADXIndicator(df['high'], df['low'], df['close'], window=14).adx()
    macd = MACD(df['close'])
    df['macd'], df['macd_signal'] = macd.macd(), macd.macd_signal()
    bb = BollingerBands(df['close'], window=20, window_dev=2)
    df['bb_upper'], df['bb_lower'] = bb.bollinger_hband(), bb.bollinger_lband()
    df['volume_ma20'] = df['volume'].rolling(window=20).mean()
    df['volume_spike'] = df['volume'] > df['volume_ma20'] * 2
    atr = AverageTrueRange(df['high'], df['low'], df['close'], window=14)
    df['atr'] = atr.average_true_range()
    return df

def enhanced_signal(df):
    latest, prev = df.iloc[-1], df.iloc[-2]
    score_long = sum([
        prev["macd"] < prev["macd_signal"] and latest["macd"] > latest["macd_signal"],
        latest["close"] > latest["ema"],
        latest["rsi"] > 48,
        latest["close"] > latest["bb_upper"],
        latest["volume_spike"],
        latest["adx"] > 15
    ])
    score_short = sum([
        prev["macd"] > prev["macd_signal"] and latest["macd"] < latest["macd_signal"],
        latest["close"] < latest["ema"],
        latest["rsi"] < 52,
        latest["close"] < latest["bb_lower"],
        latest["volume_spike"],
        latest["adx"] > 15
    ])
    if score_long >= 3: return "LONG"
    if score_short >= 3: return "SHORT"
    return ""

def get_sleep_duration_for_1m_candle():
    now = datetime.now(timezone.utc)
    seconds_past_minute = now.second + now.microsecond / 1_000_000
    return max(0.1, 60 - seconds_past_minute)

def main_loop():
    while True:
        try:
            for symbol in SYMBOLS:
                df = get_klines(symbol, INTERVAL, LIMIT)
                if df.empty or len(df) < 20:
                    continue

                df = calculate_indicators(df)
                signal = enhanced_signal(df)
                latest = df.iloc[-1]
                entry_price = latest["close"]

                balance = get_futures_balance()
                leverage = get_dynamic_leverage(balance)
                risk_pct = get_dynamic_risk_pct(balance)

                set_leverage(symbol, leverage)

                if signal and not position_exists(symbol, signal):
                    # Tutup posisi lawan dulu
                    close_opposite_position(symbol, signal)

                    # Eksekusi trade sesuai signal dengan parameter sesuai trade.py
                    success = execute_trade(
                        symbol=symbol,
                        signal=signal,
                        leverage=leverage,
                        risk=risk_pct,
                        trailing_stop=True
                    )

                    if success:
                        kirim_notifikasi_order(symbol, signal, leverage, "qty calculated internally")
                        print(f"✅ Order executed: {signal} {symbol}")
                    else:
                        print(f"❌ Gagal eksekusi order {symbol}")
                else:
                    print(f"ℹ️ Tidak ada sinyal baru atau posisi sudah terbuka: {symbol}")

            time.sleep(get_sleep_duration_for_1m_candle())

        except Exception as e:
            print(f"[ERROR LOOP] {e}")
            with open("errors.log", "a") as f:
                f.write(f"[{datetime.utcnow()}] ERROR: {str(e)}\n")
            time.sleep(30)

if __name__ == "__main__":
    main_loop()
