from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import unquote
import json
import random
import string
import httpx
import asyncio
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://quizingo.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Konstanten
# ----------------------------

TIMER_SEKUNDEN = 20
BINGOS_ZUM_GEWINNEN = 3

QUIRK_DEFINITIONEN = {
    "gluecksfeld": {
        "name": "Glücksfeld",
        "icon": "🎲",
        "beschreibung": "Markiert sofort ein zufälliges eigenes Feld",
        "kosten": 30,
        "cooldown": 3,
        "verfuegbar_fuer": "alle",
        "nur_vor_antwort": False,
    },
    "feldwahl": {
        "name": "Feldwahl",
        "icon": "🎯",
        "beschreibung": "Markiere ein selbst gewähltes freies Feld",
        "kosten": 45,
        "cooldown": 4,
        "verfuegbar_fuer": "alle",
        "nur_vor_antwort": False,
    },
    "blockade": {
        "name": "Blockade",
        "icon": "🚫",
        "beschreibung": "Verhindert das nächste Feldmarkieren bei einem Zielspieler",
        "kosten": 20,
        "cooldown": 2,
        "verfuegbar_fuer": "alle",
        "nur_vor_antwort": False,
    },
    "joker": {
        "name": "Joker",
        "icon": "🃏",
        "beschreibung": "Reduziert aktive Frage auf 2 Antwortmöglichkeiten",
        "kosten": 15,
        "cooldown": 2,
        "verfuegbar_fuer": "alle",
        "nur_vor_antwort": True,
    },
    "sabotage_klein": {
        "name": "Sabotage S",
        "icon": "💸",
        "beschreibung": "Alle anderen Spieler verlieren 15 Coins",
        "kosten": 10,
        "cooldown": 3,
        "verfuegbar_fuer": "untere_haelfte",
        "nur_vor_antwort": False,
    },
    "sabotage_gross": {
        "name": "Sabotage L",
        "icon": "💣",
        "beschreibung": "Alle anderen Spieler verlieren 25 Coins",
        "kosten": 15,
        "cooldown": 3,
        "verfuegbar_fuer": "untere_haelfte",
        "nur_vor_antwort": False,
    },
    "zeitdieb": {
        "name": "Zeitdieb",
        "icon": "⏱️",
        "beschreibung": "Reduziert den Timer für alle anderen auf 5 Sekunden",
        "kosten": 25,
        "cooldown": 4,
        "verfuegbar_fuer": "obere_haelfte",
        "nur_vor_antwort": False,
    },
    "schutzschild": {
        "name": "Schutzschild",
        "icon": "🛡️",
        "beschreibung": "Schützt einmalig vor Blockade oder Sabotage",
        "kosten": 15,
        "cooldown": 2,
        "verfuegbar_fuer": "alle",
        "nur_vor_antwort": False,
    },
    "dreifachpunkte": {
        "name": "Dreifachpunkte",
        "icon": "✨",
        "beschreibung": "Nächste Antwort gibt 3x Coins – nur für aktive Frage",
        "kosten": 20,
        "cooldown": 3,
        "verfuegbar_fuer": "alle",
        "nur_vor_antwort": True,
    },
}

# ----------------------------
# Hilfsfunktionen
# ----------------------------

def decodeURIComponent(s: str) -> str:
    return unquote(s)

def generiere_raum_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

def generiere_board():
    zahlen = list(range(1, 26))
    random.shuffle(zahlen)
    return zahlen

def berechne_bingos(markiert: list[int]) -> int:
    linien = [
        [0,1,2,3,4], [5,6,7,8,9], [10,11,12,13,14],
        [15,16,17,18,19], [20,21,22,23,24],
        [0,5,10,15,20], [1,6,11,16,21], [2,7,12,17,22],
        [3,8,13,18,23], [4,9,14,19,24],
        [0,6,12,18,24], [4,8,12,16,20],
    ]
    markiert_set = set(markiert)
    return sum(1 for linie in linien if all(i in markiert_set for i in linie))

def felder_bis_naechstes_bingo(markiert: list[int]) -> int:
    linien = [
        [0,1,2,3,4], [5,6,7,8,9], [10,11,12,13,14],
        [15,16,17,18,19], [20,21,22,23,24],
        [0,5,10,15,20], [1,6,11,16,21], [2,7,12,17,22],
        [3,8,13,18,23], [4,9,14,19,24],
        [0,6,12,18,24], [4,8,12,16,20],
    ]
    markiert_set = set(markiert)
    min_fehlend = 5
    for linie in linien:
        fehlend = sum(1 for i in linie if i not in markiert_set)
        if fehlend < min_fehlend:
            min_fehlend = fehlend
    return min_fehlend

def berechne_ranking(raum: dict) -> list[dict]:
    spieler_liste = []
    for sid, s in raum["spieler"].items():
        if not isinstance(s, dict) or "websocket" not in s:
            continue
        bingos = berechne_bingos(s["markiert"])
        spieler_liste.append({
            "id": sid,
            "name": s["name"],
            "coins": s["coins"],
            "bingos": bingos,
            "felder_bis_bingo": felder_bis_naechstes_bingo(s["markiert"]),
            "markiert_anzahl": len(s["markiert"]),
        })
    # Sortierung: Bingos absteigend, dann markierte Felder absteigend
    spieler_liste.sort(key=lambda x: (-x["bingos"], -x["markiert_anzahl"]))
    for i, s in enumerate(spieler_liste):
        s["rang"] = i + 1
    return spieler_liste

def ist_quirk_verfuegbar(quirk_id: str, spieler_id: str, raum: dict, hat_geantwortet: bool) -> tuple[bool, str]:
    spieler = raum["spieler"][spieler_id]
    quirk = QUIRK_DEFINITIONEN.get(quirk_id)

    if not quirk:
        return False, "Unbekannter Quirk"
    if spieler["coins"] < quirk["kosten"]:
        return False, "Nicht genug Coins"
    if (spieler["quirk_cooldowns"].get(quirk_id, 0)) > 0:
        return False, f"Noch {spieler['quirk_cooldowns'][quirk_id]} Fragen Cooldown"
    if quirk["nur_vor_antwort"] and hat_geantwortet:
        return False, "Nur vor der Antwort einsetzbar"

    verfuegbar_fuer = quirk["verfuegbar_fuer"]
    if verfuegbar_fuer != "alle":
        ranking = berechne_ranking(raum)
        anzahl_spieler = len(ranking)
        spieler_rang = next((s["rang"] for s in ranking if s["id"] == spieler_id), 1)
        haelfte = anzahl_spieler / 2
        if verfuegbar_fuer == "untere_haelfte" and spieler_rang <= haelfte:
            return False, "Nur für hintere Spieler verfügbar"
        if verfuegbar_fuer == "obere_haelfte" and spieler_rang > haelfte:
            return False, "Nur für vordere Spieler verfügbar"

    return True, ""

def berechne_coins(sekunden_gebraucht: float, alle_richtig_anzahl: int, alle_spieler_anzahl: int) -> int:
    basis = 10
    # Schnelligkeitsbonus: max 10 Coins bei sofortiger Antwort
    schnelligkeit = max(0, int(10 * (1 - sekunden_gebraucht / TIMER_SEKUNDEN)))
    # Seltenheitsbonus: ≤25% haben richtig geantwortet
    seltenheit = 5 if alle_spieler_anzahl > 0 and alle_richtig_anzahl / alle_spieler_anzahl <= 0.25 else 0
    return basis + schnelligkeit + seltenheit

raeume: dict = {}

# ----------------------------
# API Fragen laden
# ----------------------------

async def lade_fragen_von_api(anzahl: int = 30) -> list:
    url = f"https://opentdb.com/api.php?amount={anzahl}&type=multiple&encode=url3986"
    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        data = res.json()

    if data["response_code"] != 0:
        return []

    fragen = []
    for item in data["results"]:
        alle_antworten = [
            *[decodeURIComponent(a) for a in item["incorrect_answers"]],
            decodeURIComponent(item["correct_answer"]),
        ]
        random.shuffle(alle_antworten)
        richtig_index = alle_antworten.index(decodeURIComponent(item["correct_answer"]))

        fragen.append({
            "frage": decodeURIComponent(item["question"]),
            "antworten": alle_antworten,
            "richtig": richtig_index,
        })
    return fragen

# ----------------------------
# Broadcast
# ----------------------------

async def broadcast(raum_code: str, nachricht: dict):
    raum = raeume.get(raum_code)
    if not raum:
        return
    for spieler in raum["spieler"].values():
        if not isinstance(spieler, dict) or "websocket" not in spieler:
            continue
        try:
            await spieler["websocket"].send_text(json.dumps(nachricht))
        except:
            pass

async def sende_an_spieler(raum_code: str, spieler_id: str, nachricht: dict):
    raum = raeume.get(raum_code)
    if not raum:
        return
    spieler = raum["spieler"].get(spieler_id)
    if spieler and "websocket" in spieler:
        try:
            await spieler["websocket"].send_text(json.dumps(nachricht))
        except:
            pass

# ----------------------------
# Spielfluss
# ----------------------------

async def sende_ranking_update(raum_code: str):
    ranking = berechne_ranking(raeume[raum_code])
    await broadcast(raum_code, {
        "typ": "ranking_update",
        "ranking": ranking,
    })

async def lade_fragen_mit_retry(anzahl: int = 20, versuche: int = 3) -> list:
    for versuch in range(versuche):
        try:
            fragen = await lade_fragen_von_api(anzahl)
            if fragen:
                return fragen
        except Exception:
            pass
        await asyncio.sleep(2 ** versuch)  # 1s, 2s, 4s
    return []

async def naechste_frage_senden(raum_code: str):
    raum = raeume.get(raum_code)
    if not raum:
        return

    if raum["aktiver_timer"] and not raum["aktiver_timer"].done():
        raum["aktiver_timer"].cancel()

    for spieler in raum["spieler"].values():
        if not isinstance(spieler, dict) or "quirk_cooldowns" not in spieler:
            continue
        for quirk_id in list(spieler["quirk_cooldowns"].keys()):
            if spieler["quirk_cooldowns"][quirk_id] > 0:
                spieler["quirk_cooldowns"][quirk_id] -= 1

    raum["antworten_diese_runde"] = set()
    raum["richtige_antworten_diese_runde"] = 0
    raum["bingo_warnung_gezeigt"] = set()
    raum["frage_start_zeit"] = time.time()
    raum["frage_index"] += 1

    # Nachladen wenn weniger als 5 Fragen übrig
    fragen_uebrig = len(raum["fragen"]) - raum["frage_index"]
    if fragen_uebrig < 5:
        await broadcast(raum_code, {
            "typ": "system_nachricht",
            "text": "Neue Fragen werden geladen...",
        })
        neue_fragen = await lade_fragen_mit_retry(20)
        if neue_fragen:
            raum["fragen"].extend(neue_fragen)
        else:
            # Fallback: bestehende Fragen mischen und wiederholen
            vorherige = raum["fragen"][:raum["frage_index"]]
            random.shuffle(vorherige)
            raum["fragen"].extend(vorherige)

    frage = raum["fragen"][raum["frage_index"]]
    await broadcast(raum_code, {
        "typ": "frage",
        "frage": frage,
        "frage_nummer": raum["frage_index"] + 1,
    })

    await sende_ranking_update(raum_code)
    task = asyncio.create_task(timer_task(raum_code))
    raum["aktiver_timer"] = task

async def timer_task(raum_code: str):
    try:
        await asyncio.sleep(TIMER_SEKUNDEN)
    except asyncio.CancelledError:
        return

    raum = raeume.get(raum_code)
    if not raum or not raum["gestartet"]:
        return

    await broadcast(raum_code, {"typ": "timer_abgelaufen"})
    await asyncio.sleep(1.5)
    await naechste_frage_senden(raum_code)

# ----------------------------
# HTTP Endpunkte
# ----------------------------

@app.post("/raum/erstellen")
async def raum_erstellen(body: dict):
    code = generiere_raum_code()
    while code in raeume:
        code = generiere_raum_code()

    fragen = await lade_fragen_von_api(30)

    raeume[code] = {
        "spieler": {},
        "fragen": fragen,
        "frage_index": 0,
        "gestartet": False,
        "antworten_diese_runde": set(),
        "richtige_antworten_diese_runde": 0,
        "frage_start_zeit": None,
        "aktiver_timer": None,
        "bingo_warnung_gezeigt": set(),
    }
    return {"code": code}

# ----------------------------
# WebSocket Endpunkt
# ----------------------------

@app.websocket("/ws/{raum_code}/{spieler_id}")
async def websocket_endpunkt(websocket: WebSocket, raum_code: str, spieler_id: str):
    await websocket.accept()

    if raum_code not in raeume:
        await websocket.send_text(json.dumps({
            "typ": "fehler",
            "nachricht": "Raum nicht gefunden"
        }))
        await websocket.close()
        return

    raum = raeume[raum_code]
    name = websocket.query_params.get("name", f"Spieler {len(raum['spieler']) + 1}")

    raum["spieler"][spieler_id] = {
        "name": name,
        "board": generiere_board(),
        "markiert": [],
        "coins": 0,
        "bingos": 0,
        "quirk_cooldowns": {qid: 0 for qid in QUIRK_DEFINITIONEN},
        "blockiert": False,
        "schutzschild_aktiv": False,
        "dreifachpunkte_aktiv": False,
        "joker_aktiv": False,
        "joker_richtig_index": None,
        "joker_antworten": None,
        "websocket": websocket,
    }

    await broadcast(raum_code, {
        "typ": "spieler_liste",
        "spieler": [
            {"id": sid, "name": s["name"]}
            for sid, s in raum["spieler"].items()
            if isinstance(s, dict) and "websocket" in s
        ]
    })

    # Quirk-Definitionen an neuen Spieler schicken
    await websocket.send_text(json.dumps({
        "typ": "quirk_definitionen",
        "quirks": QUIRK_DEFINITIONEN,
    }))

    if raum["gestartet"]:
        frage = raum["fragen"][raum["frage_index"]]
        await websocket.send_text(json.dumps({
            "typ": "frage",
            "frage": frage,
            "frage_nummer": raum["frage_index"] + 1,
        }))

    try:
        while True:
            data = await websocket.receive_text()
            nachricht = json.loads(data)

            # ---- Spiel starten ----
            if nachricht["typ"] == "spiel_starten":
                raum["gestartet"] = True
                raum["frage_index"] = 0
                raum["antworten_diese_runde"] = set()
                raum["richtige_antworten_diese_runde"] = 0
                raum["frage_start_zeit"] = time.time()
                frage = raum["fragen"][0]
                await broadcast(raum_code, {
                    "typ": "frage",
                    "frage": frage,
                    "frage_nummer": 1,
                })
                await sende_ranking_update(raum_code)
                task = asyncio.create_task(timer_task(raum_code))
                raum["aktiver_timer"] = task

            # ---- Antwort ----
            elif nachricht["typ"] == "antwort":
                spieler = raum["spieler"][spieler_id]

                if spieler_id in raum["antworten_diese_runde"]:
                    continue

                raum["antworten_diese_runde"].add(spieler_id)
                frage = raum["fragen"][raum["frage_index"]]
                richtig = nachricht["antwort_index"] == frage["richtig"]

                if spieler["joker_aktiv"]:
                    richtig = nachricht["antwort_index"] == spieler["joker_richtig_index"]
                    spieler["joker_aktiv"] = False
                    spieler["joker_richtig_index"] = None
                    spieler["joker_antworten"] = None
                else:
                    richtig = nachricht["antwort_index"] == frage["richtig"]

                if richtig:
                    raum["richtige_antworten_diese_runde"] += 1
                    sekunden = time.time() - (raum["frage_start_zeit"] or time.time())
                    coins = berechne_coins(sekunden, raum["richtige_antworten_diese_runde"], len(raum["spieler"]))

                    if spieler["dreifachpunkte_aktiv"]:
                        coins *= 3
                        spieler["dreifachpunkte_aktiv"] = False

                    spieler["coins"] += coins

                    if spieler["blockiert"]:
                        spieler["blockiert"] = False
                        await sende_an_spieler(raum_code, spieler_id, {"typ": "blockade_ausgeloest"})
                    else:
                        frei = [i for i in range(25) if i not in spieler["markiert"]]
                        if frei:
                            spieler["markiert"].append(random.choice(frei))

                    neue_bingos = berechne_bingos(spieler["markiert"])
                    if neue_bingos > spieler["bingos"]:
                        spieler["bingos"] = neue_bingos
                        await broadcast(raum_code, {
                            "typ": "bingo_nachricht",
                            "spieler_name": spieler["name"],
                            "bingo_anzahl": neue_bingos,
                        })
                        if neue_bingos >= BINGOS_ZUM_GEWINNEN:
                            if raum["aktiver_timer"] and not raum["aktiver_timer"].done():
                                raum["aktiver_timer"].cancel()
                            await broadcast(raum_code, {"typ": "bingo", "gewinner": spieler["name"]})
                            continue

                    # Warnung nur einmal pro Spieler anzeigen
                    if (felder_bis_naechstes_bingo(spieler["markiert"]) == 1
                            and spieler_id not in raum["bingo_warnung_gezeigt"]):
                        raum["bingo_warnung_gezeigt"].add(spieler_id)
                        await broadcast(raum_code, {
                            "typ": "bingo_warnung",
                            "spieler_name": spieler["name"],
                        })

                await sende_an_spieler(raum_code, spieler_id, {
                    "typ": "board_update",
                    "markiert": spieler["markiert"],
                    "richtig": richtig,
                    "coins": spieler["coins"],
                    "dreifachpunkte_aktiv": spieler["dreifachpunkte_aktiv"],
                })

                await sende_ranking_update(raum_code)

                if raum["antworten_diese_runde"] >= set(raum["spieler"].keys()):
                    if raum["aktiver_timer"] and not raum["aktiver_timer"].done():
                        raum["aktiver_timer"].cancel()
                    await asyncio.sleep(1.5)
                    await naechste_frage_senden(raum_code)

            # ---- Quirk einsetzen ----
            elif nachricht["typ"] == "quirk":
                quirk_id = nachricht.get("quirk_id")
                ziel_id = nachricht.get("ziel_id")
                feld_index = nachricht.get("feld_index")
                spieler = raum["spieler"][spieler_id]
                hat_geantwortet = spieler_id in raum["antworten_diese_runde"]

                verfuegbar, fehler = ist_quirk_verfuegbar(quirk_id, spieler_id, raum, hat_geantwortet)
                if not verfuegbar:
                    await sende_an_spieler(raum_code, spieler_id, {
                        "typ": "quirk_fehler", "nachricht": fehler
                    })
                    continue

                quirk = QUIRK_DEFINITIONEN[quirk_id]
                spieler["coins"] -= quirk["kosten"]
                spieler["quirk_cooldowns"][quirk_id] = quirk["cooldown"]

                if quirk_id == "feldwahl":
                    if feld_index is not None and feld_index not in spieler["markiert"]:
                        spieler["markiert"].append(feld_index)
                        neue_bingos = berechne_bingos(spieler["markiert"])
                        if neue_bingos > spieler["bingos"]:
                            spieler["bingos"] = neue_bingos
                            await broadcast(raum_code, {
                                "typ": "bingo_nachricht",
                                "spieler_name": spieler["name"],
                                "bingo_anzahl": neue_bingos,
                            })
                            if neue_bingos >= BINGOS_ZUM_GEWINNEN:
                                await broadcast(raum_code, {"typ": "bingo", "gewinner": spieler["name"]})
                                continue
                        await sende_an_spieler(raum_code, spieler_id, {
                            "typ": "board_update",
                            "markiert": spieler["markiert"],
                            "richtig": None,
                            "coins": spieler["coins"],
                            "dreifachpunkte_aktiv": spieler["dreifachpunkte_aktiv"],
                        })
                    else:
                        # Kein Feld angegeben → Frontend soll Modal öffnen
                        await sende_an_spieler(raum_code, spieler_id, {
                            "typ": "feldwahl_aktiv",
                            "markiert": spieler["markiert"],
                        })
                        # Kosten und Cooldown rückgängig machen bis Feld gewählt
                        spieler["coins"] += quirk["kosten"]
                        spieler["quirk_cooldowns"][quirk_id] = 0
                        continue

                elif quirk_id == "dreifachpunkte":
                    spieler["dreifachpunkte_aktiv"] = True
                    await sende_an_spieler(raum_code, spieler_id, {"typ": "dreifachpunkte_aktiv"})

                elif quirk_id == "joker":
                    if spieler_id not in raum["antworten_diese_runde"]:
                        frage = raum["fragen"][raum["frage_index"]]
                        richtig_antwort = frage["antworten"][frage["richtig"]]
                        falsche = [a for a in frage["antworten"] if a != richtig_antwort]
                        zwei_optionen = [richtig_antwort, random.choice(falsche)]
                        random.shuffle(zwei_optionen)
                        richtig_in_joker = zwei_optionen.index(richtig_antwort)
                        
                        # Joker-Mapping speichern damit Antwort korrekt gewertet wird
                        spieler["joker_aktiv"] = True
                        spieler["joker_richtig_index"] = richtig_in_joker
                        spieler["joker_antworten"] = zwei_optionen

                        await sende_an_spieler(raum_code, spieler_id, {
                            "typ": "joker_aktiv",
                            "antworten": zwei_optionen,
                            "richtig": richtig_in_joker,
                        })
                    else:
                        await sende_an_spieler(raum_code, spieler_id, {
                            "typ": "quirk_fehler",
                            "nachricht": "Du hast diese Frage bereits beantwortet"
                        })
                    continue

                await sende_an_spieler(raum_code, spieler_id, {
                    "typ": "quirk_verwendet",
                    "quirk_id": quirk_id,
                    "coins": spieler["coins"],
                    "cooldowns": spieler["quirk_cooldowns"],
                })
                await sende_ranking_update(raum_code)

    except WebSocketDisconnect:
        del raum["spieler"][spieler_id]
        await broadcast(raum_code, {
            "typ": "spieler_liste",
            "spieler": [
                {"id": sid, "name": s["name"]}
                for sid, s in raum["spieler"].items()
                if isinstance(s, dict) and "websocket" in s
            ]
        })
        await sende_ranking_update(raum_code)