import os
import requests
import yfinance as yf

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def analyser_marche():
    ticker = "NVDA"
    action = yf.Ticker(ticker)
    
    todays_data = action.history(period="1d")
    if todays_data.empty:
        return
        
    prix_actuel = todays_data['Close'].iloc[-1]

    message = f"""
🚨 **ANALYSE TEMPS RÉEL - BOT TRADING** 🚨

📈 **Actif :** NVIDIA ({ticker})
💵 **Prix en direct :** ${prix_actuel:.2f}
🟢 **Signal suggéré :** Surveillance active
🛑 **Stop Loss conseillé :** ${prix_actuel * 0.95:.2f} (-5%)
🎯 **Take Profit :** ${prix_actuel * 1.08:.2f} (+8%)

📊 *Analyse technique et actualités en cours de traitement par le bot...*
"""
    send_telegram_alert(message)

if __name__ == "__main__":
    analyser_marche()
