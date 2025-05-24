import os
import time
import requests
from binance.client import Client
from dotenv import load_dotenv

load_dotenv()

client = Client(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Enhanced send_telegram with debugging
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"[DEBUG] Telegram status: {res.status_code}")
        print(f"[DEBUG] Telegram response: {res.text}")
        if res.status_code != 200:
            print(f"❌ Gagal kirim Telegram: {res.text}")
        else:
            data = res.json()
            if not data.get("ok"):
                print(f"❌ Telegram API error: {data}")
            else:
                print("✅ Notifikasi Telegram berhasil dikirim.")
    except Exception as e:
        print(f"❌ Telegram request exception: {e}")

# Utility functions omitted for brevity...
# For debug, we'll send a test message on startup

if __name__ == '__main__':
    print("🚀 Starting debug of Telegram notification...")
    test_msg = "[TEST] Bot connected!"  
    send_telegram(test_msg)
    print("🛑 Debug complete.")
