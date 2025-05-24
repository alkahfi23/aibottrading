import os
from binance.client import Client
from binance.enums import *

client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET"))

def position_exists(symbol, signal):
    positions = client.futures_position_information(symbol=symbol)
    for p in positions:
        pos_amt = float(p['positionAmt'])
        if signal == "LONG" and pos_amt > 0:
            return True
        if signal == "SHORT" and pos_amt < 0:
            return True
    return False

def close_opposite_position(symbol, signal):
    try:
        positions = client.futures_position_information(symbol=symbol)
        for p in positions:
            pos_amt = float(p['positionAmt'])
            if signal == "LONG" and pos_amt < 0:
                qty = abs(pos_amt)
                order = client.futures_create_order(
                    symbol=symbol,
                    side=SIDE_BUY,
                    type=ORDER_TYPE_MARKET,
                    quantity=qty,
                    reduceOnly=True,
                    positionSide="SHORT"
                )
                print(f"Closed SHORT position: {order}")
            elif signal == "SHORT" and pos_amt > 0:
                qty = abs(pos_amt)
                order = client.futures_create_order(
                    symbol=symbol,
                    side=SIDE_SELL,
                    type=ORDER_TYPE_MARKET,
                    quantity=qty,
                    reduceOnly=True,
                    positionSide="LONG"
                )
                print(f"Closed LONG position: {order}")
    except Exception as e:
        print(f"Failed to close opposite position: {e}")

def adjust_quantity(symbol, qty):
    # Binance minimum qty and step size from exchange info
    info = client.futures_exchange_info()
    for s in info['symbols']:
        if s['symbol'] == symbol:
            filters = s['filters']
            for f in filters:
                if f['filterType'] == 'LOT_SIZE':
                    step_size = float(f['stepSize'])
                    min_qty = float(f['minQty'])
                    break
            else:
                step_size = 0.001
                min_qty = 0.001
            break
    else:
        step_size = 0.001
        min_qty = 0.001

    # Adjust qty to step size
    adjusted_qty = (qty // step_size) * step_size
    if adjusted_qty < min_qty:
        adjusted_qty = 0
    return round(adjusted_qty, 6)

def execute_trade(symbol, side, quantity, entry_price, leverage, position_side, sl_price=None, tp_price=None, trailing_stop_callback_rate=None):
    try:
        # Set leverage before order
        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        # Place market order
        order = client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "LONG" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
            positionSide=position_side,
            reduceOnly=False
        )
        print(f"Market order executed: {order}")

        # Set SL and TP
        if sl_price or tp_price:
            params = {
                "symbol": symbol,
                "positionSide": position_side,
                "type": "STOP_MARKET",
                "stopPrice": sl_price,
                "closePosition": True,
                "side": SIDE_SELL if side == "LONG" else SIDE_BUY,
                "quantity": None,
                "reduceOnly": True
            }
            if sl_price:
                client.futures_create_order(**params)
                print(f"Stop Loss order set at {sl_price}")
            if tp_price:
                tp_params = params.copy()
                tp_params.update({
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": tp_price,
                })
                client.futures_create_order(**tp_params)
                print(f"Take Profit order set at {tp_price}")

        # Trailing stop (optional)
        if trailing_stop_callback_rate:
            client.futures_create_order(
                symbol=symbol,
                side=SIDE_SELL if side == "LONG" else SIDE_BUY,
                type="TRAILING_STOP_MARKET",
                callbackRate=trailing_stop_callback_rate,
                quantity=quantity,
                reduceOnly=True,
                positionSide=position_side
            )
            print(f"Trailing stop set with callback rate {trailing_stop_callback_rate}%")

        return True
    except Exception as e:
        print(f"Trade execution failed: {e}")
        return False
