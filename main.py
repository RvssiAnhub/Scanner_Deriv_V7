import asyncio
import websockets
import json
import pandas as pd
import requests
from datetime import datetime

# =============================================================
# 1. CONFIGURACIÓN SNIPER INTRADÍA
# =============================================================
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'
APP_ID = '1089'  

MERCADOS_FVG = {
    "Vol 10": "R_10", "Vol 25": "R_25", "Vol 50": "R_50", "Vol 75": "R_75", "Vol 100": "R_100",
    "Vol 10(1s)": "1HZ10V", "Vol 25(1s)": "1HZ25V", "Vol 50(1s)": "1HZ50V", "Vol 75(1s)": "1HZ75V", "Vol 100(1s)": "1HZ100V",
    "Jump 10": "JD10", "Jump 25": "JD25", "Jump 50": "JD50", "Jump 75": "JD75", "Jump 100": "JD100",
    "Step": "stpRNG", "XAUUSD": "frxXAUUSD", "BTCUSD": "cryBTCUSD", "US Tech 100": "OTC_US100"
}

TF_GATILLO = "5M"  
TFS = {"1M": 60, "5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}
alertas_enviadas = {}

# =============================================================
# 2. FUNCIONES DE APOYO
# =============================================================
def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}, timeout=5)
    except: pass

async def pedir_velas(ws, sid, tf_sec, count=15):
    req = {"ticks_history": sid, "count": count, "end": "latest", "style": "candles", "granularity": tf_sec}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data and data["candles"]:
        df = pd.DataFrame(data["candles"])
        for c in ['close', 'high', 'low', 'open']: df[c] = df[c].astype(float)
        return df
    return None

async def obtener_tendencia_pa(ws, sid, tf_sec):
    df = await pedir_velas(ws, sid, tf_sec, count=4)
    if df is None or len(df) < 3: return "⚪"
    c1, c2 = df.iloc[-3], df.iloc[-2]
    if c2['high'] > c1['high'] and c2['low'] > c1['low']: return "🟢"
    elif c2['high'] < c1['high'] and c2['low'] < c1['low']: return "🔴"
    else: return "🟢" if c2['close'] > c2['open'] else "🔴"

# =============================================================
# 3. LÓGICA DE DETECCIÓN, MITIGACIÓN Y ANTI-SPAM
# =============================================================
async def analizar_fvg_intraday(ws, nombre, sid):
    global alertas_enviadas
    df = await pedir_velas(ws, sid, TFS[TF_GATILLO], count=20)
    if df is None or len(df) < 10: return

    vela_actual = df.iloc[-1]
    vela_previa = df.iloc[-2]
    
    señal, color_señal, fvg_top, fvg_bot, precio_entrada = None, "", 0, 0, 0
    alerta_id = ""

    for i in range(2, len(df) - 2):
        v1, v3 = df.iloc[i-2], df.iloc[i]
        
        # 🟢 FVG ALCISTA Detectado
        if v1['high'] < v3['low']:
            top, bot = v3['low'], v1['high']
            id_temporal = f"{sid}_COMPRA_{top}_{bot}" # ID Único basado en las coordenadas del FVG
            
            if id_temporal in alertas_enviadas:
                continue # Si ya enviamos este FVG, lo saltamos y evitamos repetir
                
            if vela_previa['low'] <= top and vela_previa['close'] > bot:
                if vela_previa['close'] > vela_previa['open']: 
                    señal, color_señal, fvg_top, fvg_bot = "COMPRA", "🟢", top, bot
                    precio_entrada = top # Entrada sugerida en el borde superior del FVG
                    alerta_id = id_temporal
                    break

        # 🔴 FVG BAJISTA Detectado
        elif v1['low'] > v3['high']:
            top, bot = v1['low'], v3['high']
            id_temporal = f"{sid}_VENTA_{top}_{bot}" # ID Único basado en las coordenadas del FVG
            
            if id_temporal in alertas_enviadas:
                continue
                
            if vela_previa['high'] >= bot and vela_previa['close'] < top:
                if vela_previa['close'] < vela_previa['open']: 
                    señal, color_señal, fvg_top, fvg_bot = "VENTA", "🔴", top, bot
                    precio_entrada = bot # Entrada sugerida en el borde inferior del FVG
                    alerta_id = id_temporal
                    break

    # =========================================================
    # 4. VALIDACIÓN ESTRUCTURAL (MACRO)
    # =========================================================
    if señal:
        t_30m = await obtener_tendencia_pa(ws, sid, TFS["30M"])
        t_1h = await obtener_tendencia_pa(ws, sid, TFS["1H"])
        t_4h = await obtener_tendencia_pa(ws, sid, TFS["4H"])

        alineado = False
        if señal == "COMPRA" and t_30m == "🟢" and t_1h == "🟢" and t_4h == "🟢":
            alineado = True
        elif señal == "VENTA" and t_30m == "🔴" and t_1h == "🔴" and t_4h == "🔴":
            alineado = True

        if alineado:
            alertas_enviadas[alerta_id] = True
            msg = (f"🎯 **FVG INTRADÍA DETECTADO ({TF_GATILLO})**\n\n"
                   f"📊 *Mercado:* `{nombre}`\n"
                   f"🔥 *Acción:* **{color_señal} {señal}**\n"
                   f"🛑 *Posible Entrada:* `{round(precio_entrada, 5)}`\n"
                   f"📍 *Precio Actual:* `{round(vela_actual['open'], 5)}`\n"
                   f"📦 *Zona de Ineficiencia:* `{round(fvg_bot, 5)} - {round(fvg_top, 5)}`\n\n"
                   f"🌎 **CONFLUENCIA ESTRUCTURAL:**\n"
                   f"• `30M:` {t_30m} ✅\n"
                   f"• `1H:`  {t_1h} ✅\n"
                   f"• `4H:`  {t_4h} ✅\n"
                   f"───────────────────\n"
                   f"💎 _Análisis profesional de mitigación completado._")
            enviar_telegram(msg)

async def loop_principal():
    uri = "wss://ws.binaryws.com/websockets/v3?app_id=" + APP_ID
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nom, sid in MERCADOS_FVG.items():
                        await analizar_fvg_intraday(ws, nom, sid)
                        await asyncio.sleep(0.1) 
                    await asyncio.sleep(5) 
        except: await asyncio.sleep(2)

if __name__ == "__main__":
    enviar_telegram(f"🛡️ **V3.2 Intraday Sniper Online**\n_Filtro Anti-Spam Activado._")
    asyncio.run(loop_principal())
