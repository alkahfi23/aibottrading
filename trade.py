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
                for f in s['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        step_size = Decimal(f['stepSize'])
                        min_qty = Decimal(f['minQty'])
                        d_qty = Decimal(str(qty)).quantize(step_size, rounding=ROUND_DOWN)
                        return float(d_qty) if d_qty >= min_qty else 0.0
    except Exception as e:
        print(f"❌ adjust_quantity error: {e}")
    return 0.0

def adjust_price(symbol, price):
    try:
        info = client.futures_exchange_info()
        for s in info['symbols']:
            if s['symbol'] == symbol:
                for f in s['filters']:
                    if f['filterType'] == 'PRICE_FILTER':
                        tick_size = Decimal(f['tickSize'])
                        d_price = Decimal(str(price)).quantize(tick_size, rounding=ROUND_DOWN)
                        return float(d_price)
    except Exception as e:
        print(f"❌ adjust_price error: {e}")
    return price

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
    sl_price = adjust_price(symbol, sl_price)
    client.futures_create_order(
        symbol=symbol,
        side=SIDE_SELL if side == "LONG" else SIDE_BUY,
        type="STOP_MARKET",
        stopPrice=sl_price,
        closePosition=True,
    )
    print(f"🔒 SL order placed at {sl_price}")

def place_tp_order(symbol, side, tp_price):
    tp_price = adjust_price(symbol, tp_price)
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
    print(f"📉 Trailing stop order placed with callback rate {callback_rate}%")

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

def execute_trade(symbol, side, quantity, entry_price=None, leverage=10, position_side="BOTH", sl_price=None, tp_price=None, trailing_stop_callback_rate=None):
    try:
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
        print(f"✅ Market order executed: orderId={order['orderId']}")

        # Ambil harga mark price setelah eksekusi order untuk referensi entry price
        current_price = float(client.futures_mark_price(symbol=symbol)['markPrice'])

        print(f"🔹 Executed Trade Details:")
        print(f"   Symbol   : {symbol}")
        print(f"   Side     : {side}")
        print(f"   Quantity : {quantity}")
        print(f"   Entry Price (Mark Price) : {current_price}")
        print(f"   Leverage : {leverage}x")

        cancel_existing_exit_orders(symbol)

        atr = calculate_atr(symbol, interval='5m', period=20)  # ATR untuk SL

        # STOP LOSS
        if sl_price is None:
            if atr:
                sl_multiplier = 1.2
                sl_price = (current_price - atr * sl_multiplier) if side == "LONG" else (current_price + atr * sl_multiplier)
                sl_price = adjust_price(symbol, sl_price)
            else:
                sl_price = (current_price * 0.995) if side == "LONG" else (current_price * 1.005)
                sl_price = adjust_price(symbol, sl_price)

        # Validasi SL agar tidak langsung trigger
        if (side == "LONG" and sl_price < current_price) or (side == "SHORT" and sl_price > current_price):
            place_sl_order(symbol, side, sl_price)
        else:
            print(f"⚠️ SL dibatalkan karena terlalu dekat (current: {current_price}, SL: {sl_price})")

        MIN_PROFIT_MARGIN = 0.0015
        atr_1m = calculate_atr(symbol, interval='1m', period=20)  # ATR untuk TP

        # TAKE PROFIT
        if tp_price is None:
            if atr_1m:
                k = 1.5
                tp_price = (current_price + max(current_price * MIN_PROFIT_MARGIN, atr_1m * k)) if side == "LONG" else (current_price - max(current_price * MIN_PROFIT_MARGIN, atr_1m * k))
                tp_price = adjust_price(symbol, tp_price)
            else:
                tp_price = (current_price * (1 + MIN_PROFIT_MARGIN)) if side == "LONG" else (current_price * (1 - MIN_PROFIT_MARGIN))
                tp_price = adjust_price(symbol, tp_price)

        place_tp_order(symbol, side, tp_price)

        # Trailing stop opsional
        if trailing_stop_callback_rate:
            place_trailing_stop(symbol, side, quantity, trailing_stop_callback_rate)

        print("✅ Trade executed successfully.")
        return True

    except Exception as e:
        print(f"❌ Error execute_trade: {e}")
        return False

# Contoh penggunaan:
# execute_trade("BTCUSDT", "LONG", 0.001, leverage=10, trailing_stop_callback_rate=0.3)
