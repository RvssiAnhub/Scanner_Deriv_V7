import asyncio
import websockets
import json
import pandas as pd
import requests
from datetime import datetime

# =============================================================
# 1. CONFIGURACIÓN PRO
# =============================================================
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'
APP_ID = '1089'  

MERCADOS_GAP = {
    "Vol 10": "R_10", "Vol 25": "R_25", "Vol 50": "R_50", "Vol 75": "R_75", "Vol 100": "R_100",
    "Jump 10": "JD10", "Jump 25": "JD25", "Jump 50": "JD50", "Jump 75": "JD75", "Jump 100": "JD100",
    "Step": "stpRNG", "XAUUSD": "frxXAUUSD", "BTCUSD": "cryBTCUSD", "US Tech 100": "OTC_US100"
}

# Temporalidades en segundos para la API
TFS = {"1M": 60, "5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}
alertas_enviadas = {}

# =============================================================
# 2. MOTOR DE COMUNICACIÓN Y DATOS
# =============================================================
def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}, timeout=5)
    except: pass

async def pedir_velas(ws, sid, tf_sec, count=10):
    req = {"ticks_history": sid, "count": count, "end": "latest", "style": "candles", "granularity": tf_sec}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data and data["candles"]:
        df = pd.DataFrame(data["candles"])
        for c in ['close', 'high', 'low', 'open']: df[c] = df[c].astype(float)
        return df
    return None

# =============================================================
# 3. ESCÁNER DE ACCIÓN DEL PRECIO (MACRO TENDENCIA)
# =============================================================
async def obtener_tendencia_pa(ws, sid, tf_sec):
    df = await pedir_velas(ws, sid, tf_sec, count=4)
    if df is None or len(df) < 3: return "⚪"
    
    # Analizamos las últimas 2 velas cerradas para ver estructura (HH/LL)
    c1 = df.iloc[-3]
    c2 = df.iloc[-2]
    
    # Lógica de Altos más Altos y Bajos más Bajos
    if c2['high'] > c1['high'] and c2['low'] > c1['low']:
        return "🟢" # Tendencia Alcista Confirmada
    elif c2['high'] < c1['high'] and c2['low'] < c1['low']:
        return "🔴" # Tendencia Bajista Confirmada
    else:
        # Si es un inside bar, usamos el cuerpo de la vela actual
        if c2['close'] > c2['open']: return "🟢"
        elif c2['close'] < c2['open']: return "🔴"
        return "⚪" # Consolidación absoluta

# =============================================================
# 4. NÚCLEO ALGORÍTMICO: GAP + CONFLUENCIA
# =============================================================
async def analizar_gap_mtf(ws, nombre, sid):
    global alertas_enviadas
    df_m1 = await pedir_velas(ws, sid, TFS["1M"], count=5)
    if df_m1 is None or len(df_m1) < 4: return

    c_base = df_m1.iloc[-4]
    c_gap = df_m1.iloc[-3]
    c_conf = df_m1.iloc[-2]
    c_actual = df_m1.iloc[-1]
    
    alerta_id = f"{sid}_GAP_{c_conf['epoch']}"
    if alerta_id in alertas_enviadas: return

    # Variables de estado
    es_base_verde = c_base['close'] > c_base['open']
    es_gap_verde = c_gap['close'] > c_gap['open']
    es_conf_verde = c_conf['close'] > c_conf['open']

    es_base_roja = c_base['close'] < c_base['open']
    es_gap_roja = c_gap['close'] < c_gap['open']
    es_conf_roja = c_conf['close'] < c_conf['open']

    min_gap = c_base['close'] * 0.00005 
    señal = None
    color_señal = ""

    # Detección GAP Alcista
    if es_base_verde and es_gap_verde and es_conf_verde:
        if (c_gap['open'] - c_base['close']) >= min_gap:
            if c_conf['low'] >= c_gap['low']:
                señal = "COMPRA"
                color_señal = "🟢"

    # Detección GAP Bajista
    if es_base_roja and es_gap_roja and es_conf_roja:
        if (c_base['close'] - c_gap['open']) >= min_gap:
            if c_conf['high'] <= c_gap['high']:
                señal = "VENTA"
                color_señal = "🔴"

    # SI HAY SEÑAL -> ACTIVAR ESCÁNER MACRO (LAZY FETCH)
    if señal:
        # Consultamos la Acción del Precio en TFs superiores
        t_5m = await obtener_tendencia_pa(ws, sid, TFS["5M"])
        t_15m = await obtener_tendencia_pa(ws, sid, TFS["15M"])
        t_30m = await obtener_tendencia_pa(ws, sid, TFS["30M"])
        t_1h = await obtener_tendencia_pa(ws, sid, TFS["1H"])
        t_4h = await obtener_tendencia_pa(ws, sid, TFS["4H"])

        # Filtro de Seguridad PRO: Requerimos que al menos 1H o 4H estén a favor de la señal
        # Si disparamos contra la tendencia macro, es suicidio financiero.
        macro_alineada = False
        if señal == "COMPRA" and (t_1h == "🟢" or t_4h == "🟢"): macro_alineada = True
        if señal == "VENTA" and (t_1h == "🔴" or t_4h == "🔴"): macro_alineada = True

        if macro_alineada:
            alertas_enviadas[alerta_id] = True
            
            msg = (f"🚀 **PATRÓN GAP + MTF CONFIRMADO** 🚀\n\n"
                   f"📊 *Mercado:* `{nombre}` | TF Señal: `1M`\n"
                   f"🎯 *Acción:* **{color_señal} {señal}**\n"
                   f"📍 *Precio de Entrada:* `{round(c_actual['open'], 5)}`\n\n"
                   f"🌎 **CONFLUENCIA ESTRUCTURAL (PA):**\n"
                   f"• `1M:`  {color_señal} (Señal Base)\n"
                   f"• `5M:`  {t_5m}\n"
                   f"• `15M:` {t_15m}\n"
                   f"• `30M:` {t_30m}\n"
                   f"• `1H:`  {t_1h}\n"
                   f"• `4H:`  {t_4h}\n"
                   f"───────────────────\n"
                   f"✅ _Filtro Macro 1H/4H Superado_")
            
            enviar_telegram(msg)

# =============================================================
# 5. EJECUCIÓN
# =============================================================
async def loop_principal():
    uri = "wss://ws.binaryws.com/websockets/v3?app_id=" + APP_ID
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nom, sid in MERCADOS_GAP.items():
                        await analizar_gap_mtf(ws, nom, sid)
                        await asyncio.sleep(0.05) 
                    await asyncio.sleep(2) 
        except Exception as e:
            await asyncio.sleep(2) 

if __name__ == "__main__":
    enviar_telegram("🛡️ **Motor PRO GAP + Confluencia (V2.0)**\n_Matriz de Acción del Precio ONLINE._\nFiltrando señales contra-tendencia en 1H y 4H.")
    asyncio.run(loop_principal())
