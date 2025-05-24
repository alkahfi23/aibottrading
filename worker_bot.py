# worker_bot.py

import os
import time
import datetime
import pandas as pd
import requests
from binance.client import Client
from ta.trend import EMAIndicator, ADXIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from datetime import datetime, timezone

from trade import execute_trade, position_exists, close_opposite_position, adjust_quantity
from notifikasi import kirim_notifikasi_order, kirim_notifikasi_penutupan
from utils import (
    get_futures_balance, set_leverage, get_dynamic_leverage,
    get_dynamic_risk_pct, get_position_info, calculate_profit_pct
)

# === KONFIGURASI ===
client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET"))
BASE_URL = "https://api.binance.com"
SYMBOLS = ["BTCUSDT"]
INTERVAL = "1m"
LIMIT = 100
MIN_QTY = 0.0001

# === UTILITAS TAMBAHAN ===
def get_sleep_duration_for_1m_candle():
    now = datetime.now(timezone.utc)
    seconds_past_minute = now.second + now.microsecond / 1_000_000
    return max(0.1, 60 - seconds_past_minute)

def get_symbol_filters(symbol):
    info = client.futures_exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            return {f['filterType']: f for f in s['filters']}
    return {}

def adjust_quantity_to_step(symbol, qty):
    filters = get_symbol_filters(symbol)
    step_size = float(filters.get("LOT_SIZE", {}).get("stepSize", 0.0001))
    precision = max(0, str(step_size)[::-1].find('.'))
    return round(qty - (qty % step_size), precision)

def is_notional_valid(symbol, qty, price):
    filters = get_symbol_filters(symbol)
    min_notional = float(filters.get("MIN_NOTIONAL", {}).get("notional", 5.0))
    return qty * price >= min_notional

# === DATA DAN INDIKATOR ===
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

# === SINYAL STRATEGI ===
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

# === PERHITUNGAN RISIKO DAN UKURAN POSISI ===
def calculate_position_size(balance, risk_pct, entry, sl, leverage):
    risk_amt = balance * (risk_pct / 100)
    sl_distance_pct = abs(entry - sl) / entry
    if sl_distance_pct == 0: return 0
    notional = (risk_amt / sl_distance_pct) * leverage
    qty = notional / entry
    return round(qty, 6)

def margin_warning(balance, pos_size, entry, leverage):
    margin_used = (pos_size * entry) / leverage
    if margin_used > balance:
        return True, "❌ Margin tidak cukup untuk membuka posisi ini."
    elif margin_used > balance * 0.9:
        return True, "⚠️ Margin call risk tinggi!"
    return False, ""

# === MAIN LOOP ===
def main_loop():
    while True:
        try:
            for symbol in SYMBOLS:
                df = get_klines(symbol, INTERVAL, LIMIT)
                if df.empty or df.shape[0] < 20:
                    print(f"⚠️ Data tidak cukup untuk {symbol}")
                    continue

                df = calculate_indicators(df)
                signal = enhanced_signal(df)
                latest = df.iloc[-1]
                entry = latest["close"]

                balance = get_futures_balance()
                leverage = get_dynamic_leverage(balance)
                risk_pct = get_dynamic_risk_pct(balance)
                set_leverage(symbol, leverage)

                if signal and not position_exists(symbol, signal):
                    sl = entry - latest['atr'] * 1.5 if signal == "LONG" else entry + latest['atr'] * 1.5
                    tp = entry + latest['atr'] * 2.5 if signal == "LONG" else entry - latest['atr'] * 2.5
                    pos_size = calculate_position_size(balance, risk_pct, entry, sl, leverage)

                    margin_used = (pos_size * entry) / leverage
                    max_margin = balance * 0.8
                    if margin_used > max_margin:
                        pos_size = (max_margin * leverage) / entry

                    pos_size = adjust_quantity_to_step(symbol, pos_size)
                    if pos_size < MIN_QTY:
                        print(f"⛔ Ukuran posisi terlalu kecil untuk {symbol} (adjusted: {pos_size})")
                        continue

                    if not is_notional_valid(symbol, pos_size, entry):
                        print(f"⛔ Notional terlalu kecil: {pos_size * entry:.2f} < min")
                        continue

                    is_margin_risk, note = margin_warning(balance, pos_size, entry, leverage)
                    if is_margin_risk:
                        print(note)
                        continue

                    close_opposite_position(symbol, signal)

                    result = execute_trade(
                        symbol=symbol,
                        side=signal,
                        quantity=pos_size,
                        entry_price=entry,
                        leverage=leverage,
                        sl_price=sl,
                        tp_price=tp,
                        trailing_stop_callback_rate=1.0
                    )

                    if result:
                        print(f"✅ Order berhasil: {signal} {symbol} Qty: {pos_size}")
                        kirim_notifikasi_order(symbol, signal, leverage, pos_size)
                    else:
                        print(f"❌ Order gagal untuk {symbol}")
                else:
                    pos_info = get_position_info(symbol)
                    if pos_info and pos_info['unRealizedProfit'] != 0:
                        profit_pct = calculate_profit_pct(
                            pos_info['entryPrice'],
                            pos_info['markPrice'],
                            "LONG" if pos_info['positionAmt'] > 0 else "SHORT"
                        )
                        if abs(profit_pct) >= 0.3:
                            kirim_notifikasi_penutupan(symbol, pos_info['unRealizedProfit'], profit_pct)

                    print(f"ℹ️ {symbol}: Tidak ada sinyal baru atau posisi sudah terbuka.")

            sleep_dur = get_sleep_duration_for_1m_candle()
            print(f"🕒 Sleeping for {sleep_dur:.2f} seconds...")
            time.sleep(sleep_dur)

        except Exception as e:
            print(f"[ERROR MAIN LOOP] {e}")
            with open("errors.log", "a") as f:
                f.write(f"[{datetime.datetime.utcnow()}] ERROR: {str(e)}\n")
            time.sleep(30)

if __name__ == "__main__":
    main_loop()
