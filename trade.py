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

def execute_trade(symbol, side, quantity, entry_price, leverage, position_side="BOTH", sl_price=None, tp_price=None, trailing_stop_callback_rate=None):
    try:
        if not validate_trend_5m(symbol, side):
            print("❌ Trade dibatalkan karena trend 5m bertentangan dengan sinyal.")
            return False

        client.futures_change_leverage(symbol=symbol, leverage=leverage)

        quantity = adjust_quantity(symbol, quantity)
        if quantity <= 0:
            print("❌ Quantity too small to execute.")
            return False

        if position_exists(symbol, side):
            print("ℹ️ Posisi sudah ada, skip close lawan.")
        else:
            close_opposite_position(symbol, side)

        order = client.futures_create_order(
            symbol=symbol,
            side=SIDE_BUY if side == "LONG" else SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
            reduceOnly=False
        )
        print(f"✅ Market order executed: {order['orderId']}")

        current_price = float(client.futures_mark_price(symbol=symbol)['markPrice'])

        if sl_price:
            if (side == "LONG" and sl_price < current_price) or (side == "SHORT" and sl_price > current_price):
                client.futures_create_order(
                    symbol=symbol,
                    side=SIDE_SELL if side == "LONG" else SIDE_BUY,
                    type="STOP_MARKET",
                    stopPrice=round(sl_price, 2),
                    closePosition=True,
                )
                print(f"🔒 SL set at {sl_price}")
            else:
                print(f"⚠️ SL dibatalkan karena akan langsung trigger (current: {current_price}, SL: {sl_price})")

        if tp_price:
            if (side == "LONG" and tp_price > current_price) or (side == "SHORT" and tp_price < current_price):
                client.futures_create_order(
                    symbol=symbol,
                    side=SIDE_SELL if side == "LONG" else SIDE_BUY,
                    type="TAKE_PROFIT_MARKET",
                    stopPrice=round(tp_price, 2),
                    closePosition=True,
                )
                print(f"🎯 TP set at {tp_price}")
            else:
                print(f"⚠️ TP dibatalkan karena akan langsung trigger (current: {current_price}, TP: {tp_price})")

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
