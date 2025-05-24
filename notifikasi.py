import os
from twilio.rest import Client as TwilioClient

twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_from = os.getenv("TWILIO_PHONE_NUMBER")
twilio_to = os.getenv("MY_WHATSAPP_NUMBER")

client = TwilioClient(twilio_sid, twilio_token)

def kirim_notifikasi_order(coin, posisi, leverage, size):
    pesan = (
        f"🚀 Trade Executed\n"
        f"Coin: {coin}\n"
        f"Posisi: {posisi}\n"
        f"Leverage: {leverage}x\n"
        f"Size: {size}"
    )
    _send_whatsapp(pesan)

def kirim_notifikasi_penutupan(coin, profit_usdt, profit_pct):
    pesan = (
        f"🔒 Posisi Ditutup\n"
        f"Coin: {coin}\n"
        f"Profit: {profit_usdt:.2f} USDT ({profit_pct:.2f}%)"
    )
    _send_whatsapp(pesan)

def _send_whatsapp(message):
    try:
        message = client.messages.create(
            from_='whatsapp:' + twilio_from,
            body=message,
            to='whatsapp:' + twilio_to
        )
        print(f"WhatsApp notification sent: SID {message.sid}")
    except Exception as e:
        print(f"Failed to send WhatsApp message: {e}")
