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

def execute_trade(symbol, side, quantity, entry_price, leverage, position_side="BOTH", sl_price=None, tp_price=None, trailing_stop_callback_rate=None):
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        quantity = adjust_quantity(symbol, quantity)
        if quantity <= 0:
            print("❌ Quantity too small to execute.")
            return False

        # Close opposite position
        close_opposite_position(symbol, side)

        # Market Order Entry
        order = client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "LONG" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
            reduceOnly=False
        )
        print(f"✅ Market order executed: {order['orderId']}")

        # SL / TP (optional)
        if sl_price:
            client.futures_create_order(
                symbol=symbol,
                side=SIDE_SELL if side == "LONG" else SIDE_BUY,
                type="STOP_MARKET",
                stopPrice=round(sl_price, 2),
                closePosition=True,
                reduceOnly=True
            )
            print(f"🔒 SL set at {sl_price}")
        if tp_price:
            client.futures_create_order(
                symbol=symbol,
                side=SIDE_SELL if side == "LONG" else SIDE_BUY,
                type="TAKE_PROFIT_MARKET",
                stopPrice=round(tp_price, 2),
                closePosition=True,
                reduceOnly=True
            )
            print(f"🎯 TP set at {tp_price}")

        # Trailing Stop (optional)
        if trailing_stop_callback_rate:
            client.futures_create_order(
                symbol=symbol,
                side=SIDE_SELL if side == "LONG" else SIDE_BUY,
                type="TRAILING_STOP_MARKET",
                quantity=quantity,
                callbackRate=trailing_stop_callback_rate,
                reduceOnly=True
            )
            print(f"📉 Trailing stop set at {trailing_stop_callback_rate}%")

        return True
    except Exception as e:
        print(f"❌ Trade execution failed: {e}")
        return False
