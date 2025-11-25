from flask import Flask, request
import telegram
import os
import time
from analyzer import analyze_pair, generate_chart
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("BOT_TOKEN")
BOT = telegram.Bot(token=TOKEN)
CHAT_COOLDOWN = {}  # {chat_id: last_request_time}

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()

    if 'message' not in data:
        return 'ok'

    chat_id = data['message']['chat']['id']
    text = data['message'].get('text', '').strip().upper()

    # Rate limit 1 min per chat
    now = time.time()
    if chat_id in CHAT_COOLDOWN and now - CHAT_COOLDOWN[chat_id] < 60:
        return 'cooldown'

    if text.endswith("USDT"):
        CHAT_COOLDOWN[chat_id] = now
        
        try:
            result = analyze_pair(text)
            chart_path = generate_chart(text)

            msg = f"*Analisa Futures {text}*\n" \
                  f"*Harga:* {result['price']}\n" \
                  f"*Sinyal:* `{result['signal']}`\n" \
                  f"*Volume Spike:* {result['volume_spike']}\n" \
                  f"*RSI:* {result['rsi']}\n" \
                  f"*MACD:* {result['macd']}\n" \
                  f"*ADX:* {result['adx']}\n" \
                  f"*EMA Trend:* {result['ema']}\n" \
                  f"*BB Width:* {result['bb_width']}\n" \
                  f"*Support:* {result['support']}\n" \
                  f"*Resistance:* {result['resistance']}\n" \
                  f"*Entry:* {result['entry']}\n" \
                  f"*SL:* {result['sl']}\n" \
                  f"*TP:* {result['tp']}\n" \
                  f"*Validasi:* `{result['valid']}`"

            keyboard = []
            if result['signal'] in ['LONG', 'SHORT']:
                url = f"https://www.binance.com/en/futures/{text}"
                keyboard.append([InlineKeyboardButton("\ud83d\udd17 Buka Pair di Binance", url=url)])

            BOT.send_message(chat_id=chat_id, text=msg, parse_mode=telegram.ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
            BOT.send_photo(chat_id=chat_id, photo=open(chart_path, 'rb'))
        
        except Exception as e:
            BOT.send_message(chat_id=chat_id, text=f"\u26a0\ufe0f Gagal analisa pair {text}: {e}")

    return 'ok'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
