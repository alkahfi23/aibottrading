# trade.py

from binance.client import Client
from binance.enums import *
import os
import math


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

def round_down(value, decimals):
    factor = 10 ** decimals
    return math.floor(value * factor) / factor

def execute_trade(symbol, signal, leverage=10, risk=0.01, trailing_stop=True):
    try:
        # Set leverage
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        # Harga sekarang
        ticker = client.futures_symbol_ticker(symbol=symbol)
        current_price = float(ticker['price'])

        # Hitung position size
        balance_info = client.futures_account_balance()
        usdt_balance = float([x for x in balance_info if x['asset'] == 'USDT'][0]['balance'])
        position_size = (usdt_balance * risk * leverage) / current_price
        qty = round_down(position_size, 3)

        entry_price = current_price
        sl_price = entry_price * 0.995 if signal == 'LONG' else entry_price * 1.005
        tp_price = entry_price * 1.02 if signal == 'LONG' else entry_price * 0.98

        order_side = SIDE_BUY if signal == 'LONG' else SIDE_SELL
        sl_side = SIDE_SELL if signal == 'LONG' else SIDE_BUY
        tp_side = SIDE_SELL if signal == 'LONG' else SIDE_BUY

        # Order Market
        client.futures_create_order(
            symbol=symbol,
            side=order_side,
            type=ORDER_TYPE_MARKET,
            quantity=qty
        )

        print(f"✅ Entry {signal} {symbol} @ {entry_price:.2f}")

        # Stop Loss
        if (signal == 'LONG' and sl_price < entry_price) or (signal == 'SHORT' and sl_price > entry_price):
            client.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type=ORDER_TYPE_STOP_MARKET,
                stopPrice=str(round(sl_price, 2)),
                closePosition=True,
                timeInForce=TIME_IN_FORCE_GTC
            )
            print(f"🔒 SL @ {sl_price:.2f}")

        # Take Profit
        if (signal == 'LONG' and tp_price > entry_price) or (signal == 'SHORT' and tp_price < entry_price):
            client.futures_create_order(
                symbol=symbol,
                side=tp_side,
                type=ORDER_TYPE_TAKE_PROFIT_MARKET,
                stopPrice=str(round(tp_price, 2)),
                closePosition=True,
                timeInForce=TIME_IN_FORCE_GTC
            )
            print(f"🎯 TP @ {tp_price:.2f}")

        # Trailing Stop (optional)
        if trailing_stop:
            callback_rate = 0.3  # trailing 0.3%
            activation_price = entry_price * 1.005 if signal == 'LONG' else entry_price * 0.995

            client.futures_create_order(
                symbol=symbol,
                side=sl_side,
                type=ORDER_TYPE_TRAILING_STOP_MARKET,
                activationPrice=str(round(activation_price, 2)),
                callbackRate=str(callback_rate),
                quantity=qty,
                reduceOnly=True
            )
            print(f"📉 Trailing Stop set at {activation_price:.2f} with {callback_rate}%")

    except Exception as e:
        print(f"❌ Error execute_trade: {e}")
        return False

    return True
