import os
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
        elif signal == "SHORT" and amt > 0:
            qty = abs(amt)
            client.futures_create_order(
                symbol=symbol,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=qty,
                reduceOnly=True
            )

def get_symbol_precision(symbol):
    info = client.futures_exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'PRICE_FILTER':
                    tick_size = Decimal(f['tickSize'])
                elif f['filterType'] == 'LOT_SIZE':
                    step_size = Decimal(f['stepSize'])
                    min_qty = Decimal(f['minQty'])
            return tick_size, step_size, min_qty
    return Decimal('0.01'), Decimal('0.001'), Decimal('0.001')

def adjust_quantity(symbol, qty):
    _, step_size, min_qty = get_symbol_precision(symbol)
    d_qty = Decimal(str(qty)).quantize(step_size, rounding=ROUND_DOWN)
    return float(d_qty) if d_qty >= min_qty else 0.0

def adjust_price(symbol, price):
    tick_size, _, _ = get_symbol_precision(symbol)
    d_price = Decimal(str(price)).quantize(tick_size, rounding=ROUND_DOWN)
    return float(d_price)

def validate_trend_5m(symbol, signal):
    klines = client.futures_klines(symbol=symbol, interval='5m', limit=20)
    closes = [float(k[4]) for k in klines]
    ema5 = sum(closes[-5:]) / 5
    ema20 = sum(closes) / 20
    return (signal == "LONG" and ema5 > ema20) or (signal == "SHORT" and ema5 < ema20)

def cancel_existing_exit_orders(symbol):
    orders = client.futures_get_open_orders(symbol=symbol)
    for order in orders:
        if order['type'] in ['STOP_MARKET', 'TAKE_PROFIT_MARKET', 'TRAILING_STOP_MARKET']:
            client.futures_cancel_order(symbol=symbol, orderId=order['orderId'])

def place_sl_order(symbol, side, sl_price):
    client.futures_create_order(
        symbol=symbol,
        side=SIDE_SELL if side == "LONG" else SIDE_BUY,
        type="STOP_MARKET",
        stopPrice=adjust_price(symbol, sl_price),
        closePosition=True,
    )

def place_tp_order(symbol, side, tp_price):
    client.futures_create_order(
        symbol=symbol,
        side=SIDE_SELL if side == "LONG" else SIDE_BUY,
        type="TAKE_PROFIT_MARKET",
        stopPrice=adjust_price(symbol, tp_price),
        closePosition=True,
    )

def place_trailing_stop(symbol, side, quantity, callback_rate):
    client.futures_create_order(
        symbol=symbol,
        side=SIDE_SELL if side == "LONG" else SIDE_BUY,
        type="TRAILING_STOP_MARKET",
        quantity=adjust_quantity(symbol, quantity),
        callbackRate=callback_rate,
        reduceOnly=True
    )

def calculate_atr(symbol, interval='1m', period=14):
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=period+1)
    trs = []
    for i in range(1, len(klines)):
        high = float(klines[i][2])
        low = float(klines[i][3])
        prev_close = float(klines[i-1][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs) / len(trs)

def determine_dynamic_leverage(symbol):
    # Contoh: bisa dihubungkan ke analisa volatility atau trend strength
    return 10  # Kamu bisa ubah menjadi lebih dinamis

def execute_trade(symbol, side, quantity, entry_price, sl_price=None, tp_price=None, trailing_stop_callback_rate=None):
    try:
        if not validate_trend_5m(symbol, side):
            print("❌ Trade dibatalkan: trend 5m tidak cocok.")
            return False

        leverage = determine_dynamic_leverage(symbol)
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        quantity = adjust_quantity(symbol, quantity)
        if quantity <= 0:
            print("❌ Quantity terlalu kecil.")
            return False

        if not position_exists(symbol, side):
            close_opposite_position(symbol, side)

        order = client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "LONG" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
            reduceOnly=False
        )
        print(f"✅ Trade executed: {order['orderId']}")

        current_price = float(client.futures_mark_price(symbol=symbol)['markPrice'])
        cancel_existing_exit_orders(symbol)

        atr_1m = calculate_atr(symbol, interval='1m', period=14)
        risk_multiplier = 1.5
        rr_ratio = 3.0

        if sl_price is None:
            sl_price = current_price - atr_1m * risk_multiplier if side == "LONG" else current_price + atr_1m * risk_multiplier
            sl_price = adjust_price(symbol, sl_price)

        place_sl_order(symbol, side, sl_price)
        print(f"🔒 SL placed at {sl_price}")

        if tp_price is None:
            risk = abs(current_price - sl_price)
            tp_price = current_price + risk * rr_ratio if side == "LONG" else current_price - risk * rr_ratio
            tp_price = adjust_price(symbol, tp_price)

        place_tp_order(symbol, side, tp_price)
        print(f"📈 TP placed at {tp_price}")

        if trailing_stop_callback_rate:
            place_trailing_stop(symbol, side, quantity, trailing_stop_callback_rate)
            print(f"📉 Trailing stop active: {trailing_stop_callback_rate}%")

        return True

    except Exception as e:
        print(f"❌ Gagal eksekusi trade: {e}")
        return False
