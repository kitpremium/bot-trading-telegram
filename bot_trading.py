import os
import re
import json
import time
import uuid
import requests
import feedparser
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = str(os.environ["CHAT_ID"])  # Corrigé pour correspondre à votre secret GitHub
API = f"https://api.telegram.org/bot{TOKEN}"

BUDGET_DEPART = 100      # € de départ
RISQUE_PAR_TRADE = 0.01  # on risque max 1 % du capital par trade
MAX_POSITION = 0.30      # max 30 % du capital sur une position
MISE_MIN = 5             # pas de trade sous 5 €
COOLDOWN_H = 4

WATCHLIST = {
    "Nvidia": ("NVDA", "Nvidia stock"),
    "Apple": ("AAPL", "Apple stock"),
    "Microsoft": ("MSFT", "Microsoft stock"),
    "Tesla": ("TSLA", "Tesla stock"),
    "Amazon": ("AMZN", "Amazon stock"),
    "Meta": ("META", "Meta stock"),
    "AMD": ("AMD", "AMD stock"),
    "TotalEnergies": ("TTE.PA", "TotalEnergies"),
    "LVMH": ("MC.PA", "LVMH stock"),
    "S&P 500": ("SPY", "S&P 500"),
    "Nasdaq": ("QQQ", "Nasdaq"),
    "Bitcoin": ("BTC-USD", "Bitcoin price"),
    "Ethereum": ("ETH-USD", "Ethereum price"),
    "Solana": ("SOL-USD", "Solana price"),
    "XRP": ("XRP-USD", "XRP price"),
    "EUR/USD": ("EURUSD=X", "EUR USD forex ECB Fed"),
    "GBP/USD": ("GBPUSD=X", "GBP USD forex Bank of England"),
    "USD/JPY": ("JPY=X", "USD JPY forex Bank of Japan"),
    "Or": ("GC=F", "gold price"),
}

POS = ["surge", "soar", "beat", "upgrade", "rally", "jump", "approval", "partnership",
       "bullish", "climb", "rise", "boost", "record high", "profit", "growth"]
NEG = ["plunge", "fall", "miss", "downgrade", "lawsuit", "probe", "recall", "loss", "cut",
       "ban", "fraud", "crash", "layoff", "warning", "down", "drop", "slump", "sell-off",
       "blow", "tumble", "sink", "tariff", "fear", "bearish"]

SPECULATIF = ["prediction", "forecast", "predicts", "could ", "should you", "will ", "?",
              "how to", "best "]

AIDE = ("Commandes :\n"
        "/portefeuille : voir tes positions et ton cash\n"
        "/vendu nom [prix] : enregistrer une vente (ex : /vendu nvidia 125.4)\n"
        "/achete nom prix mise : enregistrer un achat à la main (ex : /achete bitcoin 67000 15)\n"
        "/cash montant : corriger ton cash (dépôt ou retrait)\n"
        "Sinon, utilise les boutons sous chaque signal.")

FICHIER_ETAT = "etat.json"


def etat_defaut():
    return {"cooldown": {}, "positions": {}, "pending": {}, "cash": float(BUDGET_DEPART),
            "depart": float(BUDGET_DEPART), "historique": [], "offset": 0}


try:
    _ancien = json.load(open(FICHIER_ETAT))
except Exception:
    _ancien = {}
etat = {k: _ancien.get(k, v) for k, v in etat_defaut().items()}


def sauver():
    json.dump(etat, open(FICHIER_ETAT, "w"), indent=1, ensure_ascii=False)


def maintenant():
    return datetime.now(timezone.utc)


def telegram(texte, boutons=None):
    payload = {"chat_id": CHAT_ID, "text": texte}
    if boutons:
        payload["reply_markup"] = {"inline_keyboard": [
            [{"text": t, "callback_data": d} for t, d in ligne] for ligne in boutons]}
    requests.post(f"{API}/sendMessage", json=payload, timeout=15)


# ---------- indicateurs ----------
def compte(texte, mots):
    return sum(1 for m in mots
               if re.search(r"\b" + re.escape(m) + r"(?:s|es|ed|d|ing|ped|ping)?\b", texte))


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(c, n=14):
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    p = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / p)


def atr(df, n=14):
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"] - df["Close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def actus(requete):
    url = f"https://news.google.com/rss/search?q={requete.replace(' ', '+')}&hl=en"
    limite = maintenant() - timedelta(hours=12)
    score, titres = 0, []
    for e in feedparser.parse(url).entries[:15]:
        try:
            if parsedate_to_datetime(e.published) < limite:
                continue
        except Exception:
            continue
        t = e.title.lower()
        if any(w in t for w in SPECULATIF):
            continue
        p, n = compte(t, POS), compte(t, NEG)
        score += (p > n) - (n > p)
        titres.append(e.title)
    return score, titres[:2]


def analyser(symbole, requete):
    i = yf.Ticker(symbole).history(period="5d", interval="5m").dropna()
    if len(i) < 60:
        return None
    ts = pd.Timestamp(i.index[-1])
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
    if pd.Timestamp.now(tz="UTC") - ts > pd.Timedelta(minutes=30):
        return None

    j = yf.Ticker(symbole).history(period="6mo", interval="1d")["Close"].dropna()
    haussier_jour = len(j) >= 50 and j.iloc[-1] > j.rolling(50).mean().iloc[-1]

    c = i["Close"]
    prix = c.iloc[-1]
    e9, e21 = ema(c, 9), ema(c, 21)
    r = rsi(c).iloc[-1]
    a = atr(i).iloc[-1]
    vm = i["Volume"].rolling(20).mean().iloc[-1]
    vol_ok = (vm == 0) or (i["Volume"].iloc[-3:].mean() > 1.2 * vm)
    cross_haut = e9.iloc[-1] > e21.iloc[-1] and (e9.iloc[-4:-1] <= e21.iloc[-4:-1]).any()
    cross_bas = e9.iloc[-1] < e21.iloc[-1] and (e9.iloc[-4:-1] >= e21.iloc[-4:-1]).any()
    trop_etire = abs(prix - e21.iloc[-1]) > 2 * a
    sn, titres = actus(requete)
    j0 = yf.Ticker(symbole).history(period="2d", interval="1d")["Close"].dropna()
    var = (prix / j0.iloc[-2] - 1) * 100 if len(j0) >= 2 else 0.0

    achat = bool(cross_haut and haussier_jour and 40 <= r <= 68 and vol_ok
                 and not trop_etire and sn >= 0)
    raisons = ["croisement haussier EMA9/EMA21 (5 min)", "au-dessus de la MM50 journalière",
               f"RSI {r:.0f} (pas surchauffé)", f"actus {sn:+d}"]
    return {"prix": float(prix), "var": float(var), "atr": float(a), "rsi": float(r),
            "cross_bas": bool(cross_bas), "achat": achat, "raisons": raisons,
            "news": sn, "titres": titres}


def deja_envoye(cle, heures=COOLDOWN_H):
    t = etat["cooldown"].get(cle)
    return bool(t) and maintenant() - datetime.fromisoformat(t) < timedelta(hours=heures)


def marquer(cle, decalage_h=0):
    etat["cooldown"][cle] = (maintenant() + timedelta(hours=decalage_h)).isoformat()


def nouveau_pending(contenu):
    pid = uuid.uuid4().hex[:6]
    contenu["t"] = maintenant().isoformat()
    etat["pending"][pid] = contenu
    return pid


def purger_pending():
    limite = maintenant() - timedelta(hours=12)
    etat["pending"] = {k: v for k, v in etat["pending"].items()
                       if datetime.fromisoformat(v["t"]) > limite}


def cle_nom(n):
    return re.sub(r"[^a-z0-9]", "", n.lower())


def chercher(texte, noms):
    k = cle_nom(texte)
    for n in noms:
        if cle_nom(n) == k:
            return n
    for n in noms:
        if cle_nom(n).startswith(k) and k:
            return n
    return None


def nombre(s):
    try:
        return float(s.replace(",", ".").replace("€", ""))
    except Exception:
        return None


def dernier_prix(symbole):
    try:
        return float(yf.Ticker(symbole).history(period="5d")["Close"].dropna().iloc[-1])
    except Exception:
        return None


def niveaux(symbole, prix):
    try:
        i = yf.Ticker(symbole).history(period="5d", interval="5m").dropna()
        a = float(atr(i).iloc[-1])
    except Exception:
        a = prix * 0.01
    if a != a or a <= 0:
        a = prix * 0.01
    return prix - 1.5 * a, prix + 2.5 * a, a


def ouvrir_position(nom, symbole, prix, stop, cible, mise, atr_):
    mise = min(mise, etat["cash"])
    if mise < 1:
        telegram("Pas assez de cash disponible pour enregistrer cet achat. Utilise /cash pour corriger ton solde.")
        return
    etat["positions"][nom] = {"symbole": symbole, "prix": prix, "stop": stop, "cible": cible,
                              "mise": mise, "atr": atr_, "be": False, "date": maintenant().isoformat()}
    etat["cash"] -= mise
    telegram(f"✅ Achat enregistré : {nom}\n{mise:.0f} € à {prix:.4g}\n"
             f"Mets un stop-loss à {stop:.4g} dans ton appli.\n"
             f"Objectif : {cible:.4g}. Je surveille la position.\nCash restant : {etat['cash']:.2f} €")


def fermer_position(nom, prix_sortie):
    p = etat["positions"].pop(nom, None)
    if not p:
        telegram(f"Je n'ai pas de position {nom} en portefeuille.")
        return
    pct = prix_sortie / p["prix"] - 1
    gain = p["mise"] * pct
    etat["cash"] += p["mise"] + gain
    etat["historique"].append({"nom": nom, "gain": round(gain, 2), "pct": round(pct * 100, 2),
                               "date": maintenant().isoformat()})
    telegram(f"{'🟢' if gain >= 0 else '🔴'} Vente enregistrée : {nom} à {prix_sortie:.4g}\n"
             f"Résultat : {pct * 100:+.1f} % ({gain:+.2f} €)\nCash disponible : {etat['cash']:.2f} €")


def texte_portefeuille():
    lignes, valeur = [], 0.0
    for nom, p in etat["positions"].items():
        prix = dernier_prix(p["symbole"]) or p["prix"]
        pct = prix / p["prix"] - 1
        val = p["mise"] * (1 + pct)
        valeur += val
        lignes.append(f"• {nom} : {p['mise']:.0f} € → {val:.2f} € ({pct * 100:+.1f} %)\n"
                      f"  entrée {p['prix']:.4g} | stop {p['stop']:.4g} | objectif {p['cible']:.4g}\n"
                      f"  pour vendre : /vendu {cle_nom(nom)}")
    total = etat["cash"] + valeur
    realise = sum(h["gain"] for h in etat["historique"])
    t = (f"💼 Portefeuille\nCash : {etat['cash']:.2f} €\nPositions : {valeur:.2f} €\n"
         f"Total : {total:.2f} € ({total - etat['depart']:+.2f} € depuis le départ)\n"
         f"Trades clôturés : {len(etat['historique'])} ({realise:+.2f} €)\n")
    return t + ("\n" + "\n".join(lignes) if lignes else "\nAucune position ouverte.")


def retirer_boutons(cb):
    try:
        requests.post(f"{API}/editMessageReplyMarkup", timeout=15, json={
            "chat_id": CHAT_ID, "message_id": cb["message"]["message_id"],
            "reply_markup": {"inline_keyboard": []}})
    except Exception:
        pass


def traiter_bouton(cb):
    action, _, pid = cb.get("data", "").partition("|")
    pend = etat["pending"].pop(pid, None)
    retirer_boutons(cb)
    if not pend:
        telegram("⌛ Ce signal a expiré ou a déjà été traité.")
    elif action == "buy" and pend["type"] == "buy":
        ouvrir_position(pend["nom"], pend["symbole"], pend["prix"], pend["stop"],
                        pend["cible"], pend["mise"], pend["atr"])
    elif action == "sell" and pend["type"] == "sell":
        fermer_position(pend["nom"], pend["prix"])
    elif action == "keep" and pend["type"] == "sell":
        marquer(pend["cle"], decalage_h=5)
        telegram(f"OK, tu gardes {pend['nom']}. Je te reparle de ce signal dans quelques heures.")
    else:
        telegram("OK, signal ignoré.")


def traiter_texte(texte):
    mots = texte.strip().split()
    if not mots:
        return
    cmd = mots[0].lower().split("@")[0]
    if cmd in ("/start", "/aide", "/help"):
        telegram(AIDE)
    elif cmd in ("/portefeuille", "/p"):
        telegram(texte_portefeuille())
    elif cmd == "/vendu" and len(mots) >= 2:
        nom = chercher(mots[1], etat["positions"])
        if not nom:
            telegram("Position introuvable. Tape /portefeuille pour voir les noms.")
            return
        prix = nombre(mots[2]) if len(mots) > 2 else dernier_prix(etat["positions"][nom]["symbole"])
        if not prix:
            telegram("Indique le prix de vente : /vendu nom prix")
            return
        fermer_position(nom, prix)
    elif cmd == "/achete" and len(mots) >= 4:
        nom = chercher(mots[1], WATCHLIST)
        prix, mise = nombre(mots[2]), nombre(mots[3])
        if not nom or not prix or not mise:
            telegram("Format : /achete nom prix mise (ex : /achete bitcoin 67000 15)")
        elif nom in etat["positions"]:
            telegram(f"{nom} est déjà dans ton portefeuille.")
        else:
            symbole = WATCHLIST[nom][0]
            stop, cible, a = niveaux(symbole, prix)
            ouvrir_position(nom, symbole, prix, stop, cible, mise, a)
    elif cmd == "/cash" and len(mots) >= 2 and nombre(mots[1]) is not None:
        nouveau = nombre(mots[1])
        etat["depart"] += nouveau - etat["cash"]
        etat["cash"] = nouveau
        telegram(f"Cash mis à jour : {nouveau:.2f} €")


def traiter_updates():
    try:
        r = requests.get(f"{API}/getUpdates", timeout=20,
                         params={"offset": etat["offset"], "timeout": 0}).json()
    except Exception as e:
        print("getUpdates :", e)
        return
    for u in r.get("result", []):
        etat["offset"] = u["update_id"] + 1
        cb = u.get("callback_query")
        if cb and str(cb["from"]["id"]) == CHAT_ID:
            traiter_bouton(cb)
        m = u.get("message")
        if m and str(m["chat"]["id"]) == CHAT_ID and "text" in m:
            traiter_texte(m["text"])


def proposer_achat(nom, symbole, a):
    cle = f"{nom}_achat"
    if deja_envoye(cle):
        return
    prix = a["prix"]
    capital = etat["cash"] + sum(p["mise"] for p in etat["positions"].values())
    stop_pct = 1.5 * a["atr"] / prix
    mise = round(min(capital * RISQUE_PAR_TRADE / stop_pct, capital * MAX_POSITION, etat["cash"]))
    if mise < MISE_MIN:
        return
    stop, cible = prix - 1.5 * a["atr"], prix + 2.5 * a["atr"]
    pid = nouveau_pending({"type": "buy", "nom": nom, "symbole": symbole, "prix": prix,
                           "stop": stop, "cible": cible, "mise": mise, "atr": a["atr"]})
    msg = (f"🟢 Signal ACHAT : {nom}\nPrix : {prix:.4g} ({a['var']:+.1f} % aujourd'hui)\n"
           "Raisons : " + " ; ".join(a["raisons"]) + "\n"
           f"Mise conseillée : {mise} € (cash dispo : {etat['cash']:.0f} €)\n"
           f"Stop-loss : {stop:.4g} | Objectif : {cible:.4g}\n")
    if a["titres"]:
        msg += "Actus : " + " | ".join(a["titres"]) + "\n"
    msg += "Signal automatique, pas un conseil financier."
    telegram(msg, [[(f"✅ J'ai acheté {mise} €", f"buy|{pid}"), ("❌ Passer", f"skip|{pid}")]])
    marquer(cle)


def surveiller(nom, pos, a):
    prix = a["prix"]
    pct = (prix / pos["prix"] - 1) * 100
    gain = pos["mise"] * pct / 100

    def alerte(cle, titre, conseil):
        if deja_envoye(cle, 1):
            return
        pid = nouveau_pending({"type": "sell", "nom": nom, "prix": prix, "cle": cle})
        telegram(f"{titre} : {nom}\nPrix : {prix:.4g} | position : {pct:+.1f} % ({gain:+.2f} €)\n{conseil}",
                 [[("✅ J'ai vendu", f"sell|{pid}"), ("🕐 Je garde", f"keep|{pid}")]])
        marquer(cle)

    if prix <= pos["stop"]:
        alerte(f"{nom}_stop", "🛑 STOP-LOSS atteint", "Vends pour limiter la perte.")
    elif prix >= pos["cible"]:
        alerte(f"{nom}_cible", "🎯 OBJECTIF atteint", "Prends tes gains : vends.")
    elif a["cross_bas"] and a["rsi"] < 60:
        alerte(f"{nom}_vente", "🔴 Signal VENTE", "Retournement baissier à court terme.")
    elif not pos["be"] and prix >= pos["prix"] + 1.5 * pos["atr"]:
        pos["be"] = True
        pos["stop"] = max(pos["stop"], pos["prix"])
        telegram(f"🔒 {nom} est en gain ({pct:+.1f} %). Remonte ton stop-loss au prix d'entrée.")


def alerte_actus(nom, a, detient):
    cle = f"{nom}_actus"
    if abs(a["news"]) >= 3 and not deja_envoye(cle):
        sens = "positif" if a["news"] > 0 else "négatif"
        suite = " (tu en détiens)" if detient else ""
        telegram(f"📰 Flux d'actus {sens} sur {nom}{suite} ({a['news']:+d})\n" + "\n".join(a["titres"]))
        marquer(cle)


def executer():
    traiter_updates()
    purger_pending()
    sauver()
    for nom, (symbole, requete) in WATCHLIST.items():
        try:
            a = analyser(symbole, requete)
        except Exception as e:
            print(f"{nom}: erreur {e}")
            continue
        if not a:
            continue
        pos = etat["positions"].get(nom)
        if pos:
            surveiller(nom, pos, a)
        elif a["achat"]:
            proposer_achat(nom, symbole, a)
        alerte_actus(nom, a, bool(pos))
        time.sleep(1)
    sauver()


if __name__ == "__main__":
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        requests.post(f"{API}/sendMessage", timeout=15, json={
            "chat_id": CHAT_ID, "text": "✅ Bot v3 connecté. Tape /aide pour les commandes."})
    executer()
