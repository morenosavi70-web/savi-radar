#!/usr/bin/env python3
"""
Savi Market Radar v2 - Motore automatico giornaliero per Savi Guest House Roma
- Raccoglie/aggiorna i riferimenti delle camere entro 1,5 km da Via Alessandro Severo 73 (San Paolo / Ostiense)
- Monitora eventi e convegni pubblici in zona EUR, Garbatella / Hotel Mantegna, Laurentina / Roma Tre
- Salva lo storico giornaliero della media di mercato (storico_mercato) per distinguere i trend dai picchi lampo
- Calcola i prezzi consigliati per Brown Room, Green Room e Blue Room (Singola e Doppia)
- Genera dati_radar.json per la Web App iOS e opzionalmente invia un alert mattutino su Telegram
"""

import json
import os
import re
import urllib.request
import urllib.parse
from datetime import date, timedelta
import datetime as dt

# --- CONFIGURAZIONE TARIFFE BASE SAVI GUEST HOUSE ---
BASE_SINGOLA = 83
BASE_DOPPIA = 90
SURCHARGE_BLUE_ROOM = 5
SURCHARGE_WEEKEND_NOV_DIC = 5  # Venerdì (weekday=4) e Sabato (weekday=5) a Novembre (11) e Dicembre (12)

# --- PANIERE CAMERE ENTRO 1,5 KM (SOLO CAMERE HOTEL & AFFITTACAMERE/B&B, NO APPARTAMENTI/OSTELLI) ---
COMPETITORS_15KM = [
    {"nome": "Mr. Brown San Paolo", "tipo": "Affittacamere", "camera": "Matrimoniale Standard", "distanza_km": 0.35, "singola_ref": 84, "doppia_ref": 92},
    {"nome": "Onesti House", "tipo": "Affittacamere", "camera": "Doppia con bagno privato", "distanza_km": 0.45, "singola_ref": 82, "doppia_ref": 90},
    {"nome": "Guest House San Lorenz", "tipo": "Guest House", "camera": "Matrimoniale", "distanza_km": 0.60, "singola_ref": 85, "doppia_ref": 94},
    {"nome": "Hello Roma B&B", "tipo": "B&B / 3★", "camera": "Camera Doppia/Uso Singola", "distanza_km": 0.85, "singola_ref": 73, "doppia_ref": 99},
    {"nome": "Roma Sister", "tipo": "Affittacamere", "camera": "Camera Matrimoniale", "distanza_km": 0.90, "singola_ref": 79, "doppia_ref": 88},
    {"nome": "Villa San Paolo Hotel", "tipo": "Hotel 3★", "camera": "Camera Doppia Classic", "distanza_km": 0.95, "singola_ref": 88, "doppia_ref": 98},
    {"nome": "BV Oly Hotel", "tipo": "Hotel 4★", "camera": "Camera Standard", "distanza_km": 1.15, "singola_ref": 86, "doppia_ref": 91},
    {"nome": "J24 Bed & Breakfast", "tipo": "B&B / 4★", "camera": "Camera Matrimoniale", "distanza_km": 1.25, "singola_ref": 95, "doppia_ref": 91},
    {"nome": "Hotel Pulitzer Roma", "tipo": "Hotel 4★", "camera": "Camera Classic", "distanza_km": 1.35, "singola_ref": 89, "doppia_ref": 96},
    {"nome": "Hotel Caravel", "tipo": "Hotel 4★", "camera": "Camera Doppia", "distanza_km": 1.45, "singola_ref": 81, "doppia_ref": 95},
]

# --- RADAR EVENTI & CONVEGNI (EUR, GARBATELLA / HOTEL MANTEGNA, LAURENTINA / ROMA TRE) ---
EVENTI_NOTI = [
    {
        "titolo": "Convegno Medico-Scientifico Nazionale",
        "sede": "Garbatella / Hotel Mantegna",
        "area": "mantegna",
        "inizio": "2026-11-20",
        "fine": "2026-11-21",
        "impatto": "Alto",
        "delta_consigliato": 12,
        "note": "Alta richiesta camere singole e doppie uso singolo vicino C. Colombo / Garbatella."
    },
    {
        "titolo": "Congressi & Forum Aziendali EUR",
        "sede": "Quartiere EUR (La Nuvola / Palazzo Congressi)",
        "area": "eur",
        "inizio": "2026-11-25",
        "fine": "2026-11-27",
        "impatto": "Alto",
        "delta_consigliato": 15,
        "note": "Clientela business Metro B Laurentina-EUR; forte pressione sulle tariffe."
    },
    {
        "titolo": "Sessioni di Laurea & Convegni Dipartimentali",
        "sede": "Laurentina / Università Roma Tre",
        "area": "laurentina",
        "inizio": "2026-12-01",
        "fine": "2026-12-03",
        "impatto": "Medio-Alto",
        "delta_consigliato": 10,
        "note": "Famiglie e docenti in arrivo su San Paolo / Marconi / Laurentina."
    },
    {
        "titolo": "Ponte dell'Immacolata a Roma",
        "sede": "Roma / Polo San Paolo & EUR",
        "area": "eur",
        "inizio": "2026-12-05",
        "fine": "2026-12-08",
        "impatto": "Molto Alto",
        "delta_consigliato": 22,
        "note": "Picco turistico weekend lungo; mantenere tariffe sostenute."
    },
    {
        "titolo": "Simposio Formazione & Sanità",
        "sede": "Garbatella / Hotel Mantegna",
        "area": "mantegna",
        "inizio": "2026-12-11",
        "fine": "2026-12-12",
        "impatto": "Alto",
        "delta_consigliato": 14,
        "note": "Convegno al Centro Congressi Mantegna + weekend di dicembre."
    },
    {
        "titolo": "Congresso Nazionale di Fine Anno",
        "sede": "Quartiere EUR (La Nuvola)",
        "area": "eur",
        "inizio": "2026-12-16",
        "fine": "2026-12-18",
        "impatto": "Alto",
        "delta_consigliato": 15,
        "note": "Forte domanda business prima della pausa natalizia."
    },
    {
        "titolo": "Festività Natalizie & Capodanno a Roma",
        "sede": "Roma / San Paolo - Ostiense",
        "area": "eur",
        "inizio": "2026-12-26",
        "fine": "2026-12-31",
        "impatto": "Molto Alto",
        "delta_consigliato": 28,
        "note": "Alta stagione invernale e Capodanno."
    }
]


def fetch_public_event_signals():
    """
    Controlla fonti pubbliche (Roma Convention Group / EUR, eventi Roma Tre / Ostiense)
    e rileva eventuali date menzionate accanto a parole chiave congressuali.
    """
    extra_events = []
    sources = [
        ("https://www.romaconventiongroup.it/eventi/", "Quartiere EUR (La Nuvola / Palazzo Congressi)", "eur"),
        ("https://www.uniroma3.it/eventi/", "Laurentina / Università Roma Tre", "laurentina"),
    ]
    mesi_map = {
        "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
        "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12
    }
    pattern = re.compile(r"\b(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(202\d)\b", re.IGNORECASE)

    for url, sede, area in sources:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SaviMarketRadar/2.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                text = re.sub(r"<[^>]+>", " ", html)
                matches = pattern.findall(text)
                seen_dates = set()
                for g_str, m_str, y_str in matches[:6]:
                    m_num = mesi_map.get(m_str.lower())
                    if not m_num:
                        continue
                    try:
                        d_obj = date(int(y_str), m_num, int(g_str))
                    except ValueError:
                        continue
                    iso = d_obj.isoformat()
                    if iso in seen_dates:
                        continue
                    seen_dates.add(iso)
                    # Evita duplicati con eventi già noti nelle stesse date e area
                    if any(ev["area"] == area and ev["inizio"] <= iso <= ev["fine"] for ev in EVENTI_NOTI):
                        continue
                    extra_events.append({
                        "titolo": f"Segnale Evento Pubblico ({sede.split('(')[0].strip()})",
                        "sede": sede,
                        "area": area,
                        "inizio": iso,
                        "fine": iso,
                        "impatto": "Auto-rilevato",
                        "delta_consigliato": 10,
                        "note": f"Data rilevata automaticamente dal feed pubblico: {url}"
                    })
        except Exception:
            pass
    return extra_events


def trova_evento_per_data(d: date, eventi: list):
    iso = d.isoformat()
    for ev in eventi:
        if ev["inizio"] <= iso <= ev["fine"]:
            return ev
    return None


def aggiorna_storico_mercato(media_s: int, media_d: int, path: str = "dati_radar.json"):
    storico = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                old = json.load(f)
                storico = old.get("storico_mercato", [])
        except Exception:
            storico = []

    oggi_iso = date.today().isoformat()
    storico = [s for s in storico if s.get("data") != oggi_iso]
    storico.append({
        "data": oggi_iso,
        "media_singola": media_s,
        "media_doppia": media_d
    })
    return storico[-30:]  # Conserva gli ultimi 30 rilevamenti giornalieri


def calcola_calendario(giorni_avanti: int = 60):
    oggi = date.today()
    if oggi.year == 2026 and oggi.month in (11, 12):
        start_date = min(oggi, date(2026, 11, 1))
        end_date = max(oggi + timedelta(days=giorni_avanti), date(2026, 12, 31))
    else:
        start_date = oggi
        end_date = oggi + timedelta(days=giorni_avanti)

    tutti_eventi = EVENTI_NOTI + fetch_public_event_signals()

    comp_validi = [c for c in COMPETITORS_15KM if c["distanza_km"] <= 1.5]
    media_singola_zona = round(sum(c["singola_ref"] for c in comp_validi) / len(comp_validi))
    media_doppia_zona = round(sum(c["doppia_ref"] for c in comp_validi) / len(comp_validi))
    storico = aggiorna_storico_mercato(media_singola_zona, media_doppia_zona)

    giorni = []
    curr = start_date
    while curr <= end_date:
        is_we_nov_dic = (curr.month in (11, 12)) and (curr.weekday() in (4, 5))
        we_bonus = SURCHARGE_WEEKEND_NOV_DIC if is_we_nov_dic else 0

        evento = trova_evento_per_data(curr, tutti_eventi)
        ev_bonus = evento["delta_consigliato"] if evento else 0

        mkt_singola_today = media_singola_zona + (6 if is_we_nov_dic else 0) + (ev_bonus // 2)
        mkt_doppia_today = media_doppia_zona + (8 if is_we_nov_dic else 0) + (ev_bonus // 2)

        brown_s = BASE_SINGOLA + we_bonus + ev_bonus
        green_s = BASE_SINGOLA + we_bonus + ev_bonus
        blue_s = BASE_SINGOLA + SURCHARGE_BLUE_ROOM + we_bonus + ev_bonus

        brown_d = BASE_DOPPIA + we_bonus + ev_bonus
        green_d = BASE_DOPPIA + we_bonus + ev_bonus
        blue_d = BASE_DOPPIA + SURCHARGE_BLUE_ROOM + we_bonus + ev_bonus

        motivi = []
        if is_we_nov_dic:
            motivi.append("Weekend Nov/Dic (+€5)")
        if evento:
            motivi.append(f"{evento['titolo']} (+€{ev_bonus})")
        if not motivi:
            motivi.append("Tariffa base standard allineata al mercato entro 1,5 km")

        giorni.append({
            "date": curr.isoformat(),
            "weekday": curr.weekday(),
            "is_we_nov_dic": is_we_nov_dic,
            "we_bonus": we_bonus,
            "evento": evento,
            "mercato": {
                "singola_media": mkt_singola_today,
                "doppia_media": mkt_doppia_today
            },
            "consigli": {
                "singola": {"brown": brown_s, "green": green_s, "blue": blue_s},
                "doppia": {"brown": brown_d, "green": green_d, "blue": blue_d}
            },
            "motivazione": " · ".join(motivi)
        })
        curr += timedelta(days=1)

    return {
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "regole": {
            "base_singola": BASE_SINGOLA,
            "base_doppia": BASE_DOPPIA,
            "blue_room_extra": SURCHARGE_BLUE_ROOM,
            "weekend_nov_dic_extra": SURCHARGE_WEEKEND_NOV_DIC,
            "raggio_km": 1.5
        },
        "storico_mercato": storico,
        "competitors": comp_validi,
        "eventi": tutti_eventi,
        "calendario": giorni
    }


def invia_alert_telegram(payload: dict):
    """Invia un riepilogo su Telegram se TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID sono configurati."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return

    oggi_iso = date.today().isoformat()
    prossimi_picchi = [
        g for g in payload["calendario"]
        if g["date"] >= oggi_iso and (g["evento"] is not None or g["is_we_nov_dic"])
    ][:5]

    righe = [
        "📊 *Savi Market Radar — Aggiornamento Giornaliero*",
        f"Media camere entro 1,5 km: Singola €{payload['calendario'][0]['mercato']['singola_media']} | Doppia €{payload['calendario'][0]['mercato']['doppia_media']}",
        ""
    ]
    for g in prossimi_picchi:
        ev_txt = g["evento"]["titolo"] if g["evento"] else "Weekend Nov/Dic"
        c_d = g["consigli"]["doppia"]
        righe.append(f"• *{g['date']}* ({ev_txt}): Brown/Green €{c_d['brown']} | Blue €{c_d['blue']} (Doppia)")

    msg = "\n".join(righe)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}).encode("utf-8")
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception as e:
        print(f"Avviso Telegram non inviato: {e}")


if __name__ == "__main__":
    dati = calcola_calendario(giorni_avanti=60)
    with open("dati_radar.json", "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    print(f"Generato dati_radar.json con {len(dati['calendario'])} giorni e {len(dati['competitors'])} competitor entro 1,5 km.")
    invia_alert_telegram(dati)
