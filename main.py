import requests
import time
import os
import logging
import threading
from datetime import datetime
from flask import Flask

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")
LIGAS = [39, 140, 78, 135, 61, 2, 253, 239, 11, 13]
HEADERS = {"x-apisports-key": API_FOOTBALL_KEY}
BASE_URL = "https://v3.football.api-sports.io"

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()])
log = logging.getLogger(__name__)

alertas_gol = set()
alertas_corner = set()
alertas_over25 = set()
estado_anterior = {}

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot running", 200

def enviar_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        log.error(f"Error Telegram: {e}")
        return False

def obtener_partidos_live():
    try:
        r = requests.get(f"{BASE_URL}/fixtures?live=all", headers=HEADERS, timeout=15)
        return r.json().get("response", [])
    except Exception as e:
        log.error(f"Error API: {e}")
        return []

def obtener_estadisticas(fixture_id):
    try:
        r = requests.get(f"{BASE_URL}/fixtures/statistics?fixture={fixture_id}", headers=HEADERS, timeout=15)
        raw = r.json().get("response", [])
        resultado = {}
        for ts in raw:
            nombre = ts["team"]["name"]
            s = {x["type"]: x["value"] for x in ts["statistics"]}
            resultado[nombre] = {
                "ataques_peli": int(s.get("Dangerous attacks") or 0),
                "tiros_totales": int(s.get("Total Shots") or 0),
                "tiros_arco": int(s.get("Shots on Goal") or 0),
                "tiros_bloqueados": int(s.get("Blocked Shots") or 0),
                "corners": int(s.get("Corner Kicks") or 0),
                "posesion": str(s.get("Ball Possession") or "0%").replace("%",""),
                "xg": float(s.get("Expected Goals") or 0.0),
            }
        return resultado
    except:
        return {}

def bot1_procesar(partido):
    fid = partido["fixture"]["id"]
    status = partido["fixture"]["status"]["short"]
    minuto = partido["fixture"]["status"]["elapsed"] or 0
    liga = partido["league"]["name"]
    pais = partido["league"]["country"]
    local = partido["teams"]["home"]["name"]
    visita = partido["teams"]["away"]["name"]
    g_local = partido["goals"]["home"] or 0
    g_visita = partido["goals"]["away"] or 0
    if status not in ("1H","2H","ET") or minuto < 10: return
    stats = obtener_estadisticas(fid)
    if not stats: return
    for equipo, goles_eq in [(local, g_local), (visita, g_visita)]:
        if equipo not in stats: continue
        s = stats[equipo]
        ap = s["ataques_peli"]; ta = s["tiros_arco"]; tt = s["tiros_totales"]
        xg = s["xg"]; pos = int(s["posesion"]); cor = s["corners"]
        xg_sin_gol = max(0.0, xg - goles_eq)
        puntos = 0; razones = []
        if xg_sin_gol >= 1.2: puntos += 3; razones.append(f"📐 xG sin convertir: <b>{xg_sin_gol:.2f}</b> — la pelota tiene que entrar")
        if ap >= 12: puntos += 3; razones.append(f"💥 {ap} ataques peligrosos — dominando el área rival")
        if ta >= 5: puntos += 2; razones.append(f"🎯 {ta} tiros al arco sin gol")
        if tt >= 8 and ta >= 3: puntos += 1; razones.append(f"🔫 {tt} tiros totales — volumen alto")
        if pos >= 60: puntos += 1; razones.append(f"🔵 {pos}% posesión")
        if cor >= 6: puntos += 1; razones.append(f"🚩 {cor} córners — presión constante")
        if puntos >= 7: nivel = "⚽🔥 GOL MUY PROBABLE"
        elif puntos >= 4: nivel = "⚽⚡ PRESIÓN ALTA — posible gol"
        else: continue
        ventana = minuto // 10
        clave = f"{fid}_gol_{equipo}_{ventana}"
        if clave in alertas_gol: continue
        rival = visita if equipo == local else local
        razones_txt = "\n".join(f"   • {r}" for r in razones)
        msg = (f"⚽ <b>{nivel}</b>\n\n🏆 {liga} ({pais})\n🆚 <b>{local} {g_local} - {g_visita} {visita}</b>\n⏱️ Minuto: <b>{minuto}'</b>\n\n🎯 Equipo atacante: <b>{equipo}</b>\n🛡️ Rival: {rival}\n\n<b>📊 Señales:</b>\n{razones_txt}\n\n📍 Puntuación: <b>{puntos}/11</b>\n🕐 {datetime.now().strftime('%H:%M:%S')}")
        if enviar_telegram(msg): alertas_gol.add(clave)

def bot2_procesar(partido):
    fid = partido["fixture"]["id"]
    status = partido["fixture"]["status"]["short"]
    minuto = partido["fixture"]["status"]["elapsed"] or 0
    liga = partido["league"]["name"]
    pais = partido["league"]["country"]
    local = partido["teams"]["home"]["name"]
    visita = partido["teams"]["away"]["name"]
    g_local = partido["goals"]["home"] or 0
    g_visita = partido["goals"]["away"] or 0
    if status not in ("1H","2H","ET") or minuto < 10: return
    stats = obtener_estadisticas(fid)
    if not stats: return
    for equipo, goles_eq, goles_rival in [(local,g_local,g_visita),(visita,g_visita,g_local)]:
        if equipo not in stats: continue
        s = stats[equipo]
        ap = s["ataques_peli"]; ta = s["tiros_arco"]; tt = s["tiros_totales"]
        tb = s["tiros_bloqueados"]; pos = int(s["posesion"])
        tiros_sin_gol = max(0, ta - goles_eq)
        key_estado = f"{fid}_{equipo}"
        ap_prev = estado_anterior.get(key_estado, {}).get("ap", 0)
        estado_anterior[key_estado] = {"ap": ap}
        incremento = ap - ap_prev
        puntos = 0; razones = []
        if tiros_sin_gol >= 5: puntos += 3; razones.append(f"🎯 {tiros_sin_gol} tiros sin gol — portero los desvía hacia córner")
        if tb >= 3: puntos += 3; razones.append(f"🛡️ {tb} tiros bloqueados — van por línea de fondo")
        if ap >= 10: puntos += 2; razones.append(f"💥 {ap} ataques peligrosos")
        if tt >= 10: puntos += 1; razones.append(f"🔫 {tt} tiros totales")
        if goles_eq < goles_rival and minuto >= 60: puntos += 2; razones.append(f"🔴 Va perdiendo en min {minuto}' — presión máxima")
        elif goles_eq < goles_rival: puntos += 1; razones.append(f"🔴 Va perdiendo — busca córners")
        if pos >= 65: puntos += 1; razones.append(f"🔵 {pos}% posesión")
        if incremento >= 3: puntos += 2; razones.insert(0, f"📈 +{incremento} ataques en este ciclo — RACHA")
        if puntos >= 8: nivel = "🚩🔥 CÓRNER MUY PROBABLE"
        elif puntos >= 5: nivel = "🚩⚡ CÓRNER PROBABLE"
        else: continue
        ventana = minuto // 8
        clave = f"{fid}_corner_{equipo}_{ventana}"
        if clave in alertas_corner: continue
        rival = visita if equipo == local else local
        razones_txt = "\n".join(f"   • {r}" for r in razones)
        msg = (f"🚩 <b>{nivel}</b>\n\n🏆 {liga} ({pais})\n🆚 <b>{local} {g_local} - {g_visita} {visita}</b>\n⏱️ Minuto: <b>{minuto}'</b>\n\n⚔️ Equipo: <b>{equipo}</b>\n🛡️ Defensa: {rival}\n\n<b>📊 Señales:</b>\n{razones_txt}\n\n📍 Puntuación: <b>{puntos}/14</b>\n🕐 {datetime.now().strftime('%H:%M:%S')}")
        if enviar_telegram(msg): alertas_corner.add(clave)

def bot3_procesar(partido):
    fid = partido["fixture"]["id"]
    status = partido["fixture"]["status"]["short"]
    minuto = partido["fixture"]["status"]["elapsed"] or 0
    liga = partido["league"]["name"]
    pais = partido["league"]["country"]
    local = partido["teams"]["home"]["name"]
    visita = partido["teams"]["away"]["name"]
    g_local = partido["goals"]["home"] or 0
    g_visita = partido["goals"]["away"] or 0
    total = g_local + g_visita
    if status not in ("1H","2H","ET") or minuto < 15: return
    if total >= 3: return
    stats = obtener_estadisticas(fid)
    if not stats: return
    xg_total = sum(stats[eq]["xg"] for eq in stats if eq in [local,visita])
    ap_total = sum(stats[eq]["ataques_peli"] for eq in stats if eq in [local,visita])
    ta_total = sum(stats[eq]["tiros_arco"] for eq in stats if eq in [local,visita])
    tt_total = sum(stats[eq]["tiros_totales"] for eq in stats if eq in [local,visita])
    cor_total = sum(stats[eq]["corners"] for eq in stats if eq in [local,visita])
    proyeccion = round((total/minuto)*90,2) if minuto > 0 else 0
    diferencia = abs(g_local - g_visita)
    puntos = 0; razones = []
    if xg_total >= 2.5: puntos += 4; razones.append(f"📐 xG combinado: <b>{xg_total:.2f}</b> — Over 2.5 en expectativa")
    elif xg_total >= 1.8: puntos += 2; razones.append(f"📐 xG combinado: <b>{xg_total:.2f}</b> — partido goleador")
    if proyeccion >= 3.5: puntos += 3; razones.append(f"🚀 Proyección: <b>{proyeccion} goles al 90'</b>")
    elif proyeccion >= 2.5: puntos += 2; razones.append(f"📈 Proyección: <b>{proyeccion} goles al 90'</b>")
    if ap_total >= 25: puntos += 2; razones.append(f"⚔️ {ap_total} ataques combinados — partido abierto")
    if ta_total - total >= 7: puntos += 2; razones.append(f"🎯 {ta_total-total} tiros sin convertir")
    if diferencia >= 2: puntos += 2; razones.append(f"🔴 Diferencia {diferencia} goles — equipo atacará a fondo")
    elif diferencia == 1: puntos += 1; razones.append(f"⚡ 1 gol diferencia — necesita empatar")
    if tt_total >= 20: puntos += 1; razones.append(f"🔫 {tt_total} tiros totales")
    if cor_total >= 10: puntos += 1; razones.append(f"🚩 {cor_total} córners totales")
    if minuto >= 60 and total <= 2: puntos += 1; razones.append(f"⏱️ Minuto {minuto}' partido abierto")
    if puntos >= 9: nivel = "📈🔥 OVER 2.5 MUY PROBABLE"
    elif puntos >= 6: nivel = "📈⚡ OVER 2.5 PROBABLE"
    elif puntos >= 4: nivel = "📈 SEÑALES DE OVER 2.5"
    else: return
    ventana = minuto // 12
    clave = f"{fid}_over25_{ventana}_{total}"
    if clave in alertas_over25: return
    xg_bar = "█"*min(int((xg_total/3.0)*10),10) + "░"*max(0,10-int((xg_total/3.0)*10))
    razones_txt = "\n".join(f"   • {r}" for r in razones)
    bloque_stats = ""
    for eq in [local,visita]:
        if eq in stats:
            s = stats[eq]
            bloque_stats += f"\n📊 <b>{eq}</b> — xG: {s['xg']:.2f} | Ataques: {s['ataques_peli']} | Al arco: {s['tiros_arco']}\n"
    msg = (f"📈 <b>{nivel}</b>\n\n🏆 {liga} ({pais})\n🆚 <b>{local} {g_local} - {g_visita} {visita}</b>\n⏱️ Minuto: <b>{minuto}'</b>\n⚽ Goles: <b>{total}</b> → Faltan <b>{max(0,3-total)}</b> para Over 2.5\n\n📐 xG combinado: <b>{xg_total:.2f}</b>\n[{xg_bar}] / 3.0\n🚀 Proyección: <b>{proyeccion} goles al 90'</b>\n\n<b>🧠 Señales:</b>\n{razones_txt}{bloque_stats}\n📍 Puntuación: <b>{puntos}/16</b>\n🕐 {datetime.now().strftime('%H:%M:%S')}")
    if enviar_telegram(msg): alertas_over25.add(clave)

def loop_bot(nombre, funcion, intervalo):
    log.info(f"{nombre} — iniciado")
    while True:
        try:
            for partido in obtener_partidos_live():
                funcion(partido)
                time.sleep(0.3)
        except Exception as e:
            log.error(f"Error {nombre}: {e}")
        time.sleep(intervalo)

def main():
    log.info("🤖 CRISA ALERTS BOT — Iniciando...")
    enviar_telegram(
        "🤖 <b>CRISA ALERTS BOT — Activo ✅</b>\n\n"
        "⚽ Bot 1 — Gol inminente\n"
        "🚩 Bot 2 — Córner inminente\n"
        "📈 Bot 3 — Over 2.5 predictivo"
    )
    hilos = [
        threading.Thread(target=loop_bot, args=("⚽Bot1", bot1_procesar, 60), daemon=True),
        threading.Thread(target=loop_bot, args=("🚩Bot2", bot2_procesar, 45), daemon=True),
        threading.Thread(target=loop_bot, args=("📈Bot3", bot3_procesar, 60), daemon=True),
        threading.Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000))), daemon=True),
    ]
    for h in hilos:
        h.start()
    log.info("✅ Los 3 bots corriendo en paralelo")
    while True:
        time.sleep(60)

if __name__ == "__main__":
    main()
