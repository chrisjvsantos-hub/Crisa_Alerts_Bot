import requests
import time
import os
import logging
import threading
from datetime import datetime
from flask import Flask

TELEGRAM_TOKEN   = os.environ.get(“TELEGRAM_TOKEN”)
TELEGRAM_CHAT_ID = os.environ.get(“TELEGRAM_CHAT_ID”)
API_FOOTBALL_KEY = os.environ.get(“API_FOOTBALL_KEY”)

LIGAS = [39, 140, 78, 135, 61, 2, 3, 848, 253, 239, 11, 13, 238, 262, 88, 244, 94, 113, 144, 119, 71]

HEADERS  = {“x-apisports-key”: API_FOOTBALL_KEY}
BASE_URL = “https://v3.football.api-sports.io”

logging.basicConfig(level=logging.INFO,
format=”%(asctime)s [%(levelname)s] %(message)s”,
handlers=[logging.StreamHandler()])
log = logging.getLogger(**name**)

alertas_gol    = set()
alertas_corner = set()
alertas_over25 = set()
estado_anterior = {}

app = Flask(**name**)

@app.route(”/”)
def home():
return “Bot running”, 200

def enviar_telegram(msg):
url = f”https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage”
try:
r = requests.post(url, json={“chat_id”: TELEGRAM_CHAT_ID, “text”: msg, “parse_mode”: “HTML”}, timeout=10)
return r.status_code == 200
except Exception as e:
log.error(f”Error Telegram: {e}”)
return False

def obtener_partidos_live():
try:
r = requests.get(f”{BASE_URL}/fixtures?live=all”, headers=HEADERS, timeout=15)
partidos = r.json().get(“response”, [])
if LIGAS:
partidos = [p for p in partidos if p[“league”][“id”] in LIGAS]
return partidos
except Exception as e:
log.error(f”Error API: {e}”)
return []

def obtener_estadisticas(fixture_id):
try:
r = requests.get(f”{BASE_URL}/fixtures/statistics?fixture={fixture_id}”, headers=HEADERS, timeout=15)
raw = r.json().get(“response”, [])
resultado = {}
for ts in raw:
nombre = ts[“team”][“name”]
s = {x[“type”]: x[“value”] for x in ts[“statistics”]}
resultado[nombre] = {
“ataques_peli”:     int(s.get(“Dangerous attacks”) or 0),
“tiros_totales”:    int(s.get(“Total Shots”) or 0),
“tiros_arco”:       int(s.get(“Shots on Goal”) or 0),
“tiros_bloqueados”: int(s.get(“Blocked Shots”) or 0),
“corners”:          int(s.get(“Corner Kicks”) or 0),
“posesion”:         str(s.get(“Ball Possession”) or “0%”).replace(”%”, “”),
“xg”:               float(s.get(“Expected Goals”) or 0.0),
“tarjetas_rojas”:   int(s.get(“Red Cards”) or 0),
}
return resultado
except Exception as e:
log.error(f”Error stats {fixture_id}: {e}”)
return {}

def hay_tarjeta_roja(stats, local, visita):
for eq in [local, visita]:
if eq in stats and stats[eq][“tarjetas_rojas”] > 0:
return True
return False

# ── BOT 1: GOL EN PRIMER TIEMPO (15’-45’) ────────────────────

def bot1_procesar(partido):
fid      = partido[“fixture”][“id”]
status   = partido[“fixture”][“status”][“short”]
minuto   = partido[“fixture”][“status”][“elapsed”] or 0
liga     = partido[“league”][“name”]
pais     = partido[“league”][“country”]
local    = partido[“teams”][“home”][“name”]
visita   = partido[“teams”][“away”][“name”]
g_local  = partido[“goals”][“home”] or 0
g_visita = partido[“goals”][“away”] or 0

```
if status != "1H": return
if minuto < 15 or minuto > 45: return

stats = obtener_estadisticas(fid)
if not stats: return
if hay_tarjeta_roja(stats, local, visita): return

for equipo, goles_eq in [(local, g_local), (visita, g_visita)]:
    if equipo not in stats: continue
    s = stats[equipo]
    ap = s["ataques_peli"]; ta = s["tiros_arco"]; tt = s["tiros_totales"]
    tb = s["tiros_bloqueados"]; pos = int(s["posesion"]); cor = s["corners"]
    xg_sin_gol = max(0.0, s["xg"] - goles_eq)

    puntos = 0; razones = []

    if xg_sin_gol >= 1.5:
        puntos += 4; razones.append(f"📐 xG sin convertir: <b>{xg_sin_gol:.2f}</b> — deuda de gol muy alta")
    elif xg_sin_gol >= 0.9:
        puntos += 2; razones.append(f"📐 xG sin convertir: <b>{xg_sin_gol:.2f}</b> — presión ofensiva clara")

    if ap >= 15:
        puntos += 3; razones.append(f"💥 {ap} ataques peligrosos — dominio total del área rival")
    elif ap >= 10:
        puntos += 2; razones.append(f"💥 {ap} ataques peligrosos — presión constante")

    if ta >= 6:
        puntos += 3; razones.append(f"🎯 {ta} tiros al arco — portero siendo bombardeado")
    elif ta >= 4:
        puntos += 2; razones.append(f"🎯 {ta} tiros al arco — volumen alto de remates")

    if tb >= 4:
        puntos += 2; razones.append(f"🛡️ {tb} tiros bloqueados — defensa siendo superada")

    if pos >= 65 and ap >= 8:
        puntos += 2; razones.append(f"🔵 {pos}% posesión + {ap} ataques — dominio total")

    if cor >= 5:
        puntos += 1; razones.append(f"🚩 {cor} córners en 1er tiempo — presión continua")

    if 30 <= minuto <= 42:
        puntos += 1; razones.append(f"⏱️ Minuto {minuto}' — zona óptima antes del descanso")

    if puntos >= 10:   nivel = "⚽🔥 GOL 1er TIEMPO MUY PROBABLE"
    elif puntos >= 8:  nivel = "⚽⚡ GOL 1er TIEMPO PROBABLE"
    else: continue

    ventana = minuto // 8
    clave   = f"{fid}_gol1t_{equipo}_{ventana}"
    if clave in alertas_gol: continue

    rival = visita if equipo == local else local
    razones_txt = "\n".join(f"   • {r}" for r in razones)

    msg = (
        f"⚽ <b>{nivel}</b>\n\n"
        f"🏆 {liga} ({pais})\n"
        f"🆚 <b>{local} {g_local} - {g_visita} {visita}</b>\n"
        f"⏱️ Minuto: <b>{minuto}'</b> — 1er Tiempo\n"
        f"🟥 Tarjetas rojas: 0 ✅\n\n"
        f"🎯 Equipo en ataque: <b>{equipo}</b>\n"
        f"🛡️ Portero bajo presión: {rival}\n\n"
        f"<b>📊 Señales de gol inminente:</b>\n"
        f"{razones_txt}\n\n"
        f"📍 Puntuación: <b>{puntos}/16</b>\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
    if enviar_telegram(msg):
        alertas_gol.add(clave)
        log.info(f"⚽ Gol 1T [{nivel}] {puntos}pts: {equipo} min {minuto}")
```

# ── BOT 2: CÓRNER INMINENTE ───────────────────────────────────

def bot2_procesar(partido):
fid      = partido[“fixture”][“id”]
status   = partido[“fixture”][“status”][“short”]
minuto   = partido[“fixture”][“status”][“elapsed”] or 0
liga     = partido[“league”][“name”]
pais     = partido[“league”][“country”]
local    = partido[“teams”][“home”][“name”]
visita   = partido[“teams”][“away”][“name”]
g_local  = partido[“goals”][“home”] or 0
g_visita = partido[“goals”][“away”] or 0

```
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
    if goles_eq == goles_rival and minuto >= 75: puntos += 1; razones.append(f"🟡 Empate en min {minuto}' — busca gol ganador")
    if pos >= 65: puntos += 1; razones.append(f"🔵 {pos}% posesión")
    if incremento >= 3: puntos += 2; razones.insert(0, f"📈 +{incremento} ataques este ciclo — RACHA ACTIVA")

    if puntos >= 8:   nivel = "🚩🔥 CÓRNER MUY PROBABLE"
    elif puntos >= 5: nivel = "🚩⚡ CÓRNER PROBABLE"
    else: continue

    ventana = minuto // 8
    clave = f"{fid}_corner_{equipo}_{ventana}"
    if clave in alertas_corner: continue

    rival = visita if equipo == local else local
    razones_txt = "\n".join(f"   • {r}" for r in razones)

    msg = (
        f"🚩 <b>{nivel}</b>\n\n"
        f"🏆 {liga} ({pais})\n"
        f"🆚 <b>{local} {g_local} - {g_visita} {visita}</b>\n"
        f"⏱️ Minuto: <b>{minuto}'</b>\n\n"
        f"⚔️ Equipo atacante: <b>{equipo}</b>\n"
        f"🛡️ Defensa bajo presión: {rival}\n\n"
        f"<b>📊 Señales de córner inminente:</b>\n"
        f"{razones_txt}\n\n"
        f"📍 Puntuación: <b>{puntos}/14</b>\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
    if enviar_telegram(msg):
        alertas_corner.add(clave)
        log.info(f"🚩 Córner [{nivel}] {puntos}pts: {equipo} min {minuto}")
```

# ── BOT 3: OVER 2.5 PREDICTIVO ───────────────────────────────

def bot3_procesar(partido):
fid      = partido[“fixture”][“id”]
status   = partido[“fixture”][“status”][“short”]
minuto   = partido[“fixture”][“status”][“elapsed”] or 0
liga     = partido[“league”][“name”]
pais     = partido[“league”][“country”]
local    = partido[“teams”][“home”][“name”]
visita   = partido[“teams”][“away”][“name”]
g_local  = partido[“goals”][“home”] or 0
g_visita = partido[“goals”][“away”] or 0
total    = g_local + g_visita

```
if status not in ("1H","2H","ET") or minuto < 15: return
if total >= 3: return

stats = obtener_estadisticas(fid)
if not stats: return
if hay_tarjeta_roja(stats, local, visita): return

xg_total  = sum(stats[eq]["xg"] for eq in stats if eq in [local,visita])
ap_total  = sum(stats[eq]["ataques_peli"] for eq in stats if eq in [local,visita])
ta_total  = sum(stats[eq]["tiros_arco"] for eq in stats if eq in [local,visita])
tt_total  = sum(stats[eq]["tiros_totales"] for eq in stats if eq in [local,visita])
cor_total = sum(stats[eq]["corners"] for eq in stats if eq in [local,visita])
tb_total  = sum(stats[eq]["tiros_bloqueados"] for eq in stats if eq in [local,visita])
proyeccion = round((total/minuto)*90, 2) if minuto > 0 else 0
diferencia = abs(g_local - g_visita)
ocasiones_sin_gol = ta_total - total

puntos = 0; razones = []

if xg_total >= 3.0:
    puntos += 5; razones.append(f"📐 xG combinado: <b>{xg_total:.2f}</b> — Over 2.5 matemáticamente superado")
elif xg_total >= 2.5:
    puntos += 4; razones.append(f"📐 xG combinado: <b>{xg_total:.2f}</b> — exactamente en la línea del Over 2.5")
elif xg_total >= 2.0:
    puntos += 3; razones.append(f"📐 xG combinado: <b>{xg_total:.2f}</b> — muy cerca del Over 2.5")
elif xg_total >= 1.5:
    puntos += 1; razones.append(f"📐 xG combinado: <b>{xg_total:.2f}</b> — producción ofensiva activa")

if proyeccion >= 4.0:
    puntos += 4; razones.append(f"🚀 Proyección: <b>{proyeccion} goles al 90'</b> — ritmo explosivo")
elif proyeccion >= 3.0:
    puntos += 3; razones.append(f"🚀 Proyección: <b>{proyeccion} goles al 90'</b> — Over 2.5 en ritmo")
elif proyeccion >= 2.5:
    puntos += 2; razones.append(f"📈 Proyección: <b>{proyeccion} goles al 90'</b>")

if ap_total >= 35:
    puntos += 3; razones.append(f"⚔️ {ap_total} ataques combinados — partido completamente abierto")
elif ap_total >= 25:
    puntos += 2; razones.append(f"⚔️ {ap_total} ataques combinados — mucha actividad ofensiva")

if ocasiones_sin_gol >= 10:
    puntos += 3; razones.append(f"🎯 {ocasiones_sin_gol} tiros sin convertir — los goles tienen que caer")
elif ocasiones_sin_gol >= 7:
    puntos += 2; razones.append(f"🎯 {ocasiones_sin_gol} tiros sin convertir — deuda ofensiva alta")

if diferencia >= 2 and minuto >= 50:
    puntos += 3; razones.append(f"🔴 Diferencia {diferencia} goles en min {minuto}' — atacará sin parar")
elif diferencia >= 2:
    puntos += 2; razones.append(f"🔴 Diferencia {diferencia} goles — equipo necesita remontar")
elif diferencia == 1 and minuto >= 60:
    puntos += 2; razones.append(f"⚡ 1 gol diferencia en min {minuto}' — partido tenso")
elif diferencia == 1:
    puntos += 1; razones.append(f"⚡ 1 gol diferencia — el que pierde necesita empatar")

if tb_total >= 8: puntos += 2; razones.append(f"🛡️ {tb_total} tiros bloqueados — defensas siendo superadas")
if tt_total >= 25: puntos += 1; razones.append(f"🔫 {tt_total} tiros totales — volumen muy alto")
if cor_total >= 12: puntos += 1; razones.append(f"🚩 {cor_total} córners — ambas defensas sufriendo")
if 55 <= minuto <= 75 and total <= 2: puntos += 1; razones.append(f"⏱️ Minuto {minuto}' — ventana ideal para el 3er gol")

if puntos >= 14:   nivel = "📈🔥 OVER 2.5 CASI SEGURO"
elif puntos >= 10: nivel = "📈🔥 OVER 2.5 MUY PROBABLE"
elif puntos >= 7:  nivel = "📈⚡ OVER 2.5 PROBABLE"
else: return

ventana = minuto // 12
clave = f"{fid}_over25_{ventana}_{total}"
if clave in alertas_over25: return

xg_bar = "█"*min(int((xg_total/3.0)*10),10) + "░"*max(0,10-int((xg_total/3.0)*10))
razones_txt = "\n".join(f"   • {r}" for r in razones)
bloque_stats = ""
for eq in [local, visita]:
    if eq in stats:
        s = stats[eq]
        bloque_stats += f"\n📊 <b>{eq}</b> — xG: {s['xg']:.2f} | Ataques: {s['ataques_peli']} | Al arco: {s['tiros_arco']}\n"

msg = (
    f"📈 <b>{nivel}</b>\n\n"
    f"🏆 {liga} ({pais})\n"
    f"🆚 <b>{local} {g_local} - {g_visita} {visita}</b>\n"
    f"⏱️ Minuto: <b>{minuto}'</b>\n"
    f"⚽ Goles: <b>{total}</b> → Faltan <b>{max(0,3-total)}</b> para Over 2.5\n"
    f"🟥 Tarjetas rojas: 0 ✅\n\n"
    f"📐 xG combinado: <b>{xg_total:.2f}</b>\n"
    f"[{xg_bar}] / 3.0\n"
    f"🚀 Proyección al 90': <b>{proyeccion} goles</b>\n\n"
    f"<b>🧠 ¿Por qué se van a marcar más goles?</b>\n"
    f"{razones_txt}"
    f"{bloque_stats}\n"
    f"📍 Puntuación: <b>{puntos}/25</b>\n"
    f"🕐 {datetime.now().strftime('%H:%M:%S')}"
)
if enviar_telegram(msg):
    alertas_over25.add(clave)
    log.info(f"📈 Over 2.5 [{nivel}] {puntos}pts xG={xg_total:.2f}: {local} vs {visita} min {minuto}")
```

# ── LOOP PRINCIPAL ────────────────────────────────────────────

def loop_bot(nombre, funcion, intervalo):
log.info(f”{nombre} — hilo iniciado”)
while True:
try:
for partido in obtener_partidos_live():
funcion(partido)
time.sleep(0.3)
except Exception as e:
log.error(f”Error {nombre}: {e}”)
time.sleep(intervalo)

def main():
log.info(“🤖 CRISA ALERTS BOT v2 — Iniciando…”)
enviar_telegram(
“🤖 <b>CRISA ALERTS BOT v2 — Activo ✅</b>\n\n”
“Parámetros mejorados para mayor precisión:\n\n”
“⚽ <b>Bot 1</b> — Gol 1er Tiempo (min 15-45)\n”
“   xG + ataques + sin tarjeta roja\n\n”
“🚩 <b>Bot 2</b> — Córner inminente\n”
“   Tiros bloqueados + rachas de ataque\n\n”
“📈 <b>Bot 3</b> — Over 2.5 predictivo\n”
“   xG combinado + proyección + sin tarjeta roja\n\n”
f”🏆 {len(LIGAS)} ligas monitoreadas”
)

```
hilos = [
    threading.Thread(target=loop_bot, args=("⚽Bot1", bot1_procesar, 55), daemon=True),
    threading.Thread(target=loop_bot, args=("🚩Bot2", bot2_procesar, 45), daemon=True),
    threading.Thread(target=loop_bot, args=("📈Bot3", bot3_procesar, 60), daemon=True),
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000))), daemon=True),
]
for h in hilos:
    h.start()
log.info("✅ Los 3 bots corriendo en paralelo")
while True:
    time.sleep(60)
```

if **name** == “**main**”:
main()
