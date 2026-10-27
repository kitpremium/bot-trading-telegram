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

# 💼 VOS POSITIONS ACTUELLES (Modifiez ici selon ce que vous avez acheté)
# Format : "TICKER": {"quantite": nombre, "prix_achat": prix_moyen}
MON_PORTEFEUILLE = {
    "NVDA": {"quantite": 1, "prix_achat": 115.00},    # Exemple : 1 action NVIDIA achetée à 115$
    "BTC-USD": {"quantite": 0.005, "prix_achat": 62000.00} # Exemple de crypto
}

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
            variation = ((prix_actuel - prix_precedent) / prix_precedent) * 100
            
            # Gestion du portefeuille
            statut_portefeuille = "❌ Vous ne possédez pas cet actif"
            if ticker in MON_PORTEFEUILLE:
                pos = MON_PORTEFEUILLE[ticker]
                qte = pos["quantite"]
                p_achat = pos["prix_achat"]
                valeur_actuelle = qte * prix_actuel
                valeur_achat = qte * p_achat
                gain_perte = valeur_actuelle - valeur_achat
                gain_perte_pct = ((prix_actuel - p_achat) / p_achat) * 100
                
                emoji_gp = "🟢" if gain_perte >= 0 else "🔴"
                statut_portefeuille = (
                    f"✅ **En portefeuille :** {qte} unité(s)\n"
                    f"💰 **Valeur :** ${valeur_actuelle:.2f}\n"
                    f"📊 **Performance :** {emoji_gp} {gain_perte_pct:+.2f}% (${gain_perte:+.2f})"
                )

            # Signal technique
            if variation > 1.5:
                signal = "🟢 ACHETER / RENFORCER"
            elif variation < -1.5:
                signal = "🔴 VENDRE / PRUDENCE"
            else:
                signal = "🟡 SURVEILLER"

            message = f"""
📊 **ANALYSE : {nom}**

💵 **Prix direct :** ${prix_actuel:.2f} ({variation:+.2f}%)
💡 **Signal Bot :** {signal}

{statut_portefeuille}
"""
            send_telegram_alert(message)
            
        except Exception as e:
            print(f"Erreur pour {ticker}: {e}")

if __name__ == "__main__":
    analyser_marche()
