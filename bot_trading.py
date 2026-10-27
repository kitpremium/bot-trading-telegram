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

# Liste des actifs à surveiller (Actions, Cryptos, Forex)
ACTIFS = {
    "NVIDIA (Action)": "NVDA",
    "Bitcoin (Crypto)": "BTC-USD",
    "Ethereum (Crypto)": "ETH-USD",
    "EUR/USD (Forex)": "EURUSD=X"
}

def analyser_marche():
    for nom, ticker in ACTIFS.items():
        try:
            action = yf.Ticker(ticker)
            hist = action.history(period="5d")
            
            if hist.empty or len(hist) < 2:
                continue
                
            prix_actuel = hist['Close'].iloc[-1]
            prix_precedent = hist['Close'].iloc[-2]
            
            # Calcul de la variation en pourcentage sur 24h / dernière bougie
            variation = ((prix_actuel - prix_precedent) / prix_precedent) * 100
            
            # Logique de signal simple basée sur le momentum
            if variation > 1.5:
                signal = "🟢 ACHETER (Forte impulsion haussière)"
                stop_loss = prix_actuel * 0.97
                take_profit = prix_actuel * 1.05
            elif variation < -1.5:
                signal = "🔴 VENDRE / ÉVITER (Tendance baissière)"
                stop_loss = prix_actuel * 1.03
                take_profit = prix_actuel * 0.95
            else:
                signal = "🟡 SURVEILLER (Marché neutre / Consolidation)"
                stop_loss = prix_actuel * 0.98
                take_profit = prix_actuel * 1.02

            message = f"""
📊 **ANALYSE TEMPS RÉEL : {nom}**

💵 **Prix :** ${prix_actuel:.2f}
📈 **Variation :** {variation:+.2f}%
💡 **Signal :** {signal}
🛑 **Stop Loss :** ${stop_loss:.2f}
🎯 **Take Profit :** ${take_profit:.2f}
"""
            send_telegram_alert(message)
            
        except Exception as e:
            print(f"Erreur pour {ticker}: {e}")

if __name__ == "__main__":
    analyser_marche()
