import os
from binance.client import Client

client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET"))

def get_futures_balance(asset="USDT"):
    """Ambil saldo USDT di akun futures"""
    try:
        balances = client.futures_account_balance()
        for b in balances:
            if b['asset'] == asset:
                return float(b['balance'])
    except Exception as e:
        print(f"❌ Gagal ambil balance futures: {e}")
    return 0.0

def set_leverage(symbol, leverage):
    """Set leverage pada symbol tertentu"""
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        print(f"✅ Leverage {leverage}x berhasil diset untuk {symbol}")
    except Exception as e:
        print(f"❌ Gagal set leverage: {e}")

def get_dynamic_leverage(balance, min_leverage=1, max_leverage=20):
    """
    Contoh fungsi leverage dinamis:
    - Balance kecil => leverage rendah
    - Balance besar => leverage tinggi
    Skala linier sederhana
    """
    if balance <= 50:
        return min_leverage
    elif balance >= 1000:
        return max_leverage
    else:
        # Linear scaling antara min dan max leverage
        leverage = min_leverage + (balance - 50) * (max_leverage - min_leverage) / (1000 - 50)
        return int(round(leverage))

def get_dynamic_risk_pct(balance, min_risk=0.005, max_risk=0.02):
    """
    Contoh risiko % dinamis:
    - Balance kecil => risiko lebih kecil (0.5%)
    - Balance besar => risiko lebih besar (2%)
    """
    if balance <= 50:
        return min_risk
    elif balance >= 1000:
        return max_risk
    else:
        risk = min_risk + (balance - 50) * (max_risk - min_risk) / (1000 - 50)
        return round(risk, 4)
