import asyncio
import websockets
import json
import pandas as pd
import requests
from datetime import datetime

# =============================================================
# 1. CONFIGURACIÓN DE IDENTIDAD Y RED
# =============================================================
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'
APP_ID = '1089'  

# Temporalidad estricta M1 (60 segundos)
TF_M1 = 60 

# Diccionario de Activos PRO (Boom y Crash ELIMINADOS)
MERCADOS_GAP = {
    "Vol 10": "R_10", "Vol 25": "R_25", "Vol 50": "R_50", "Vol 75": "R_75", "Vol 100": "R_100",
    "Vol 10(1s)": "1HZ10V", "Vol 25(1s)": "1HZ25V", "Vol 50(1s)": "1HZ50V", "Vol 75(1s)": "1HZ75V", "Vol 100(1s)": "1HZ100V",
    "Jump 10": "JD10", "Jump 25": "JD25", "Jump 50": "JD50", "Jump 75": "JD75", "Jump 100": "JD100",
    "Step": "stpRNG", "Step 200": "STEP200", "Step 500": "STEP500", 
    "DEX 900 UP": "DEX900UP", "DEX 900 DN": "DEX900DN",
    "XAUUSD": "frxXAUUSD", "BTCUSD": "cryBTCUSD", "US Tech 100": "OTC_US100", "Wall Street 30": "OTC_US30"
}

alertas_enviadas = {}

# =============================================================
# 2. MOTOR DE COMUNICACIÓN
# =============================================================
def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}, timeout=5)
    except: pass

async def pedir_velas(ws, sid):
    req = {"ticks_history": sid, "count": 10, "end": "latest", "style": "candles", "granularity": TF_M1}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data and data["candles"]:
        df = pd.DataFrame(data["candles"])
        for c in ['close', 'high', 'low', 'open']: df[c] = df[c].astype(float)
        return df
    return None

# =============================================================
# 3. NÚCLEO ALGORÍTMICO: ESTRATEGIA DE CONTINUIDAD GAP
# =============================================================
async def analizar_gap_m1(ws, nombre, sid):
    global alertas_enviadas
    df = await pedir_velas(ws, sid)
    if df is None or len(df) < 5: return

    # Extraemos las velas clave para el análisis de patrón
    # c_actual es la vela en formación (índice -1)
    # Analizamos las 3 velas cerradas anteriores:
    c_base = df.iloc[-4]   # Vela previa a la formación del GAP
    c_gap = df.iloc[-3]    # Primera vela después del GAP
    c_conf = df.iloc[-2]   # Segunda vela de confirmación (recién cerrada)
    c_actual = df.iloc[-1]
    
    # Identificador único para evitar alertas duplicadas en el mismo minuto
    alerta_id = f"{sid}_GAP_{c_conf['epoch']}"
    if alerta_id in alertas_enviadas: return

    # Variables de estado y color de velas
    es_base_verde = c_base['close'] > c_base['open']
    es_gap_verde = c_gap['close'] > c_gap['open']
    es_conf_verde = c_conf['close'] > c_conf['open']

    es_base_roja = c_base['close'] < c_base['open']
    es_gap_roja = c_gap['close'] < c_gap['open']
    es_conf_roja = c_conf['close'] < c_conf['open']

    # Filtro Dinámico de Ruido: Requerimos un GAP claro (distancia mínima de precio)
    # Evitamos micro-movimientos que no representan fuerza institucional
    precio_promedio = c_base['close']
    min_gap = precio_promedio * 0.00005 # 0.005% del precio como GAP mínimo

    señal = None
    tipo_gap = ""

    # LÓGICA ALCISTA
    if es_base_verde and es_gap_verde and es_conf_verde:
        # Existe un GAP alcista válido entre el cierre base y apertura gap
        if (c_gap['open'] - c_base['close']) >= min_gap:
            # Regla de Oro: La 2da vela no rompe el mínimo de la vela previa
            if c_conf['low'] >= c_gap['low']:
                señal = "🟢 COMPRA"
                tipo_gap = "Continuidad Alcista"

    # LÓGICA BAJISTA
    if es_base_roja and es_gap_roja and es_conf_roja:
        # Existe un GAP bajista válido
        if (c_base['close'] - c_gap['open']) >= min_gap:
            # Regla de Oro: La 2da vela no rompe el máximo de la vela previa
            if c_conf['high'] <= c_gap['high']:
                señal = "🔴 VENTA"
                tipo_gap = "Continuidad Bajista"

    # EMISIÓN DE LA SEÑAL
    if señal:
        alertas_enviadas[alerta_id] = True
        
        msg = (f"🚀 **PATRÓN GAP DETECTADO** 🚀\n\n"
               f"📊 *Mercado:* `{nombre}` | TF: `M1`\n"
               f"🎯 *Acción:* **{señal}**\n\n"
               f"🧩 *Estructura:* `{tipo_gap}`\n"
               f"✅ *Condición:* `Regla de las 2 Velas Cumplida`\n"
               f"📍 *Precio de Entrada:* `{round(c_actual['open'], 5)}`\n"
               f"───────────────────\n"
               f"⏰ _{datetime.now().strftime('%H:%M:%S UTC')}_")
        
        enviar_telegram(msg)

# =============================================================
# 4. MATRIZ DE EJECUCIÓN ASÍNCRONA
# =============================================================
async def loop_principal():
    uri = "wss://ws.binaryws.com/websockets/v3?app_id=" + APP_ID
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nom, sid in MERCADOS_GAP.items():
                        await analizar_gap_m1(ws, nom, sid)
                        # Retraso ultra-corto para M1
                        await asyncio.sleep(0.05) 
                    # Escaneo completo agresivo cada 3 segundos
                    await asyncio.sleep(3) 
        except Exception as e:
            # Reconexión silenciosa
            await asyncio.sleep(2) 

if __name__ == "__main__":
    enviar_telegram("🛡️ **Motor PRO de Continuidad GAP (V1.0)**\n_Inicializando matriz M1..._\nMercados Activos: Volatility, Jump, Step, Forex, Cripto.\nEstatus: Escaneo Institucional de 2 Velas ONLINE.")
    asyncio.run(loop_principal())
