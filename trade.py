import os
import time
from decimal import Decimal, ROUND_DOWN
from binance.client import Client
from binance.enums import *

client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET"))

def position_exists(symbol, signal):
    positions = client.futures_position_information(symbol=symbol)
    for p in positions:
        amt = float(p['positionAmt'])
        if signal == "LONG" and amt > 0:
            return True
        if signal == "SHORT" and amt < 0:
            return True
    return False

def close_opposite_position(symbol, signal):
    try:
        positions = client.futures_position_information(symbol=symbol)
        for p in positions:
            amt = float(p['positionAmt'])
            if signal == "LONG" and amt < 0:
                qty = abs(amt)
                client.futures_create_order(
                    symbol=symbol,
                    side=SIDE_BUY,
                    type=ORDER_TYPE_MARKET,
                    quantity=qty,
                    reduceOnly=True
                )
                print(f"✅ Closed SHORT position of {qty}")
            elif signal == "SHORT" and amt > 0:
                qty = abs(amt)
                client.futures_create_order(
                    symbol=symbol,
                    side=SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=qty,
                    reduceOnly=True
                )
                print(f"✅ Closed LONG position of {qty}")
    except Exception as e:
        print(f"❌ Failed to close opposite: {e}")

def adjust_quantity(symbol, qty):
    try:
        info = client.futures_exchange_info()
        for s in info['symbols']:
            if s['symbol'] == symbol:
                step_size = None
                min_qty = None
                for f in s['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        step_size = Decimal(f['stepSize'])
                        min_qty = Decimal(f['minQty'])
                        break
                if step_size is None or min_qty is None:
                    print("❌ Tidak ditemukan filter LOT_SIZE.")
                    return 0.0
                d_qty = Decimal(str(qty)).quantize(step_size, rounding=ROUND_DOWN)
                if d_qty < min_qty:
                    return 0.0
                return float(d_qty)
    except Exception as e:
        print(f"❌ adjust_quantity error: {e}")
    return 0.0

def validate_trend_5m(symbol, signal):
    try:
        klines = client.futures_klines(symbol=symbol, interval='5m', limit=20)
        closes = [float(k[4]) for k in klines]
        ema5 = sum(closes[-5:]) / 5
        ema20 = sum(closes) / 20
        if signal == "LONG" and ema5 > ema20:
            return True
        elif signal == "SHORT" and ema5 < ema20:
            return True
        else:
            print(f"⚠️ Sinyal 1m ditolak karena trend 5m tidak mendukung (EMA5={ema5:.2f}, EMA20={ema20:.2f})")
            return False
    except Exception as e:
        print(f"❌ Gagal validasi trend 5m: {e}")
        return False

def cancel_existing_exit_orders(symbol):
    try:
        orders = client.futures_get_open_orders(symbol=symbol)
        for order in orders:
            if order['type'] in ['STOP_MARKET', 'TAKE_PROFIT_MARKET', 'TRAILING_STOP_MARKET']:
                client.futures_cancel_order(symbol=symbol, orderId=order['orderId'])
                print(f"🗑️ Cancelled {order['type']} order ID {order['orderId']}")
    except Exception as e:
        print(f"❌ Gagal membatalkan order TP/SL/Trailing: {e}")

def place_sl_order(symbol, side, sl_price):
    sl_price = adjust_price_to_tick(symbol, sl_price, side)
    client.futures_create_order(
        symbol=symbol,
        side=SIDE_SELL if side == "LONG" else SIDE_BUY,
        type="STOP_MARKET",
        stopPrice=sl_price,
        closePosition=True,
    )
    print(f"🔒 SL order placed at {sl_price}")

def place_tp_order(symbol, side, tp_price):
    tp_price = adjust_price_to_tick(symbol, tp_price, side)
    client.futures_create_order(
        symbol=symbol,
        side=SIDE_SELL if side == "LONG" else SIDE_BUY,
        type="TAKE_PROFIT_MARKET",
        stopPrice=tp_price,
        closePosition=True,
    )
    print(f"📈 TP order placed at {tp_price}")

def place_trailing_stop(symbol, side, quantity, callback_rate):
    client.futures_create_order(
        symbol=symbol,
        side=SIDE_SELL if side == "LONG" else SIDE_BUY,
        type="TRAILING_STOP_MARKET",
        quantity=quantity,
        callbackRate=callback_rate,
        reduceOnly=True
    )
    print(f"📉 Trailing stop set at {callback_rate}%")

def calculate_atr(symbol, interval='5m', period=20):
    try:
        klines = client.futures_klines(symbol=symbol, interval=interval, limit=period+1)
        trs = []
        for i in range(1, len(klines)):
            high = float(klines[i][2])
            low = float(klines[i][3])
            prev_close = float(klines[i-1][4])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        atr = sum(trs) / len(trs)
        return atr
    except Exception as e:
        print(f"❌ Gagal hitung ATR: {e}")
        return None

def get_tick_size(symbol):
    try:
        info = client.futures_exchange_info()
        for s in info['symbols']:
            if s['symbol'] == symbol:
                for f in s['filters']:
                    if f['filterType'] == 'PRICE_FILTER':
                        return Decimal(f['tickSize'])
    except Exception as e:
        print(f"❌ Gagal dapat tickSize: {e}")
    return Decimal("0.01")

def adjust_price_to_tick(symbol, price, side):
    tick_size = get_tick_size(symbol)
    d_price = Decimal(str(price))
    if side == "LONG":
        # Untuk LONG, round down supaya SL di bawah harga
        adjusted = d_price.quantize(tick_size, rounding=ROUND_DOWN)
    else:
        # Untuk SHORT, round up supaya SL di atas harga
        adjusted = d_price.quantize(tick_size, rounding=ROUND_DOWN)
    return float(adjusted)

def get_balance():
    try:
        balance_info = client.futures_account_balance()
        for b in balance_info:
            if b['asset'] == 'USDT':
                return float(b['balance'])
    except Exception as e:
        print(f"❌ Gagal mengambil balance: {e}")
    return 1000  # fallback

def calculate_dynamic_leverage(symbol, side, entry_price, sl_price, risk_perc=0.01):
    balance = get_balance()
    risk_amount = balance * risk_perc

    price_diff = abs(entry_price - sl_price)
    if price_diff == 0:
        return 1  # minimal leverage

    max_position_value = risk_amount / price_diff

    leverage = max_position_value / balance
    leverage = min(leverage, 125)
    leverage = max(leverage, 1)

    return round(leverage)

def execute_trade(symbol, side, quantity, entry_price=None, leverage=None, position_side="BOTH", sl_price=None, tp_price=None, trailing_stop_callback_rate=None):
    try:
        atr = calculate_atr(symbol, interval='5m', period=20)

        # Hitung leverage dinamis kalau entry_price dan sl_price tersedia dan leverage tidak diset
        if entry_price and sl_price and leverage is None:
            leverage = calculate_dynamic_leverage(symbol, side, entry_price, sl_price)
            print(f"⚙️ Leverage dinamis dihitung: {leverage}")

        if leverage is None:
            leverage = 10  # default leverage

        if not validate_trend_5m(symbol, side):
            print("❌ Trade dibatalkan karena trend 5m bertentangan dengan sinyal.")
            return False

        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        quantity = adjust_quantity(symbol, quantity)
        if quantity <= 0:
            print("❌ Quantity too small to execute.")
            return False

        if not position_exists(symbol, side):
            close_opposite_position(symbol, side)
        else:
            print("ℹ️ Posisi sudah ada, skip close lawan.")

        order = client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "LONG" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
            reduceOnly=False
        )
        print(f"✅ Market order executed: {order['orderId']}")

        current_price = float(client.futures_mark_price(symbol=symbol)['markPrice'])

        cancel_existing_exit_orders(symbol)

        # STOP LOSS ADAPTIF
        if sl_price is None:
            if atr:
                sl_multiplier = 1.2
                if side == "LONG":
                    sl_price = current_price - atr * sl_multiplier
                else:
                    sl_price = current_price + atr * sl_multiplier
                print(f"🔒 SL adaptif berdasarkan ATR: {sl_price:.2f}")
            else:
                sl_price = current_price * (1 - 0.005) if side == "LONG" else current_price * (1 + 0.005)
                print(f"🔒 SL fallback: {sl_price:.2f}")

        # Validasi dan set SL order
        if (side == "LONG" and sl_price < current_price) or (side == "SHORT" and sl_price > current_price):
            place_sl_order(symbol, side, sl_price)
        else:
            print(f"⚠️ SL dibatalkan karena SL tidak valid (harga saat ini: {current_price}, SL: {sl_price})")

        MIN_PROFIT_MARGIN = 0.0015
        atr_1m = calculate_atr(symbol, interval='1m', period=20)

        if tp_price is None:
            if atr_1m:
                k = 1.5
                if side == "LONG":
                    tp_price = current_price + max(current_price * MIN_PROFIT_MARGIN, atr_1m * k)
                else:
                    tp_price = current_price - max(current_price * MIN_PROFIT_MARGIN, atr_1m * k)
                print(f"📈 TP adaptif berdasarkan ATR: {tp_price:.2f}")
            else:
                if side == "LONG":
                    tp_price = current_price * (1 + MIN_PROFIT_MARGIN)
                else:
                    tp_price = current_price * (1 - MIN_PROFIT_MARGIN)
                print(f"📈 TP fallback: {tp_price:.2f}")

        place_tp_order(symbol, side, tp_price)

        if trailing_stop_callback_rate:
            place_trailing_stop(symbol, side, quantity, trailing_stop_callback_rate)
            print(f"📉 Trailing stop set at {trailing_stop_callback_rate}%")

        return True
    except Exception as e:
        print(f"❌ Trade execution failed: {e}")
        return False
