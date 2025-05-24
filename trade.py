# trade.py

from binance.client import Client
from binance.enums import *
import os

client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET"))

def adjust_quantity(symbol, qty):
    info = client.futures_exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            step = float([f for f in s['filters'] if f['filterType'] == 'LOT_SIZE'][0]['stepSize'])
            precision = max(0, str(step)[::-1].find('.'))
            return round(qty - (qty % step), precision)
    return qty

def set_leverage(symbol, leverage):
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
    except Exception as e:
        print(f"❌ Gagal set leverage: {e}")

def close_opposite_position(symbol, direction):
    pos = client.futures_position_information(symbol=symbol)
    for p in pos:
        amt = float(p['positionAmt'])
        if direction == "LONG" and amt < 0:
            client.futures_create_order(
                symbol=symbol, side=SIDE_BUY, type=ORDER_TYPE_MARKET, quantity=abs(amt)
            )
        elif direction == "SHORT" and amt > 0:
            client.futures_create_order(
                symbol=symbol, side=SIDE_SELL, type=ORDER_TYPE_MARKET, quantity=abs(amt)
            )

def position_exists(symbol, direction):
    pos = client.futures_position_information(symbol=symbol)
    for p in pos:
        amt = float(p['positionAmt'])
        if direction == "LONG" and amt > 0:
            return True
        elif direction == "SHORT" and amt < 0:
            return True
    return False

def execute_trade(symbol, side, quantity, entry_price, leverage, sl_price, tp_price, trailing_stop_callback_rate=0.8):
    try:
        side_enum = SIDE_BUY if side == "LONG" else SIDE_SELL
        opposite = SIDE_SELL if side_enum == SIDE_BUY else SIDE_BUY

        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        client.futures_create_order(
            symbol=symbol,
            side=side_enum,
            type=ORDER_TYPE_MARKET,
            quantity=quantity
        )

        client.futures_create_order(
            symbol=symbol,
            side=opposite,
            type=ORDER_TYPE_STOP_MARKET,
            stopPrice=round(sl_price, 2),
            closePosition=True,
            timeInForce=TIME_IN_FORCE_GTC
        )

        client.futures_create_order(
            symbol=symbol,
            side=opposite,
            type=ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=round(tp_price, 2),
            closePosition=True,
            timeInForce=TIME_IN_FORCE_GTC
        )

        client.futures_create_order(
            symbol=symbol,
            side=opposite,
            type=ORDER_TYPE_TRAILING_STOP_MARKET,
            callbackRate=trailing_stop_callback_rate,
            activationPrice=round(entry_price, 2),
            closePosition=True
        )

        return True
    except Exception as e:
        print(f"❌ Error execute_trade: {e}")
        return False
