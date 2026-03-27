import asyncio
import websockets
import json
import pandas as pd
import requests
from telegram.ext import Application
from datetime import datetime

# --- CONFIGURACIÓN DE IDENTIDAD ---
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'
APP_ID = '1089'

alertas_enviadas = {}

# --- LISTADO EXPANDIDO DE MERCADOS ---
SIMBOLOS_API = {
    "Boom 1000": "BOOM1000", "Boom 900": "BOOM900", "Boom 600": "BOOM600", "Boom 500": "BOOM500", "Boom 300": "BOOM300",
    "Crash 1000": "CRASH1000", "Crash 900": "CRASH900", "Crash 600": "CRASH600", "Crash 500": "CRASH500", "Crash 300": "CRASH300",
    "Vol 10": "R_10", "Vol 25": "R_25", "Vol 50": "R_50", "Vol 75": "R_75", "Vol 100": "R_100",
    "Vol 10(1s)": "1HZ10V", "Vol 25(1s)": "1HZ25V", "Vol 50(1s)": "1HZ50V", "Vol 75(1s)": "1HZ75V", "Vol 100(1s)": "1HZ100V",
    "Jump 10": "JD10", "Jump 25": "JD25", "Jump 50": "JD50", "Jump 75": "JD75", "Jump 100": "JD100",
    "Step": "stpRNG", "Step 200": "STEP200", "Step 300": "STEP300", "Step 500": "STEP500",
    "MultiStep 2": "STP_2", "MultiStep 3": "STP_3", "DEX 600 UP": "DEX600UP", "DEX 600 DN": "DEX600DN",
    "DEX 900 UP": "DEX900UP", "DEX 900 DN": "DEX900DN", "XAUUSD": "frxXAUUSD", "BTCUSD": "cryBTCUSD",
    "US Tech 100": "OTC_US100", "Wall Street 30": "OTC_US30"
}

# --- TEMPORALIDADES SOLICITADAS ---
TFS_SCAN = {"15M": 900, "30M": 1800, "1H": 3600, "4H": 14400, "1D": 86400}

def enviar_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except: pass

async def pedir_velas(ws, api_id, tf_sec, count=300):
    req = {"ticks_history": api_id, "count": count, "end": "latest", "style": "candles", "granularity": tf_sec}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data:
        df = pd.DataFrame(data["candles"])
        for c in ['close', 'high', 'low']: df[c] = df[c].astype(float)
        return df
    return None

async def obtener_mapa_confluencia(ws, api_id):
    mapa = ""
    for n, v in TFS_SCAN.items():
        df = await pedir_velas(ws, api_id, v, 150)
        if df is not None:
            e30 = df['close'].ewm(span=30, adjust=False).mean().iloc[-1]
            e50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
            e100 = df['close'].ewm(span=100, adjust=False).mean().iloc[-1]
            if e30 > e50 > e100: mapa += f"• {n}: 🟢 Abanico Alcista\n"
            elif e30 < e50 < e100: mapa += f"• {n}: 🔴 Abanico Bajista\n"
            else: mapa += f"• {n}: ⚪ Sin Tendencia Clara\n"
    return mapa

async def analizar_estrategia(ws, nombre, api_id, tf_n, tf_v):
    global alertas_enviadas
    clave = f"{nombre}_{tf_n}"
    
    df = await pedir_velas(ws, api_id, tf_v, 150)
    if df is None or len(df) < 120: return

    # Cálculo exacto de EMAs
    df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
    
    # SEPARACIÓN DE VELAS: Ignoramos la actual en movimiento. Solo miramos la que acaba de CERRAR.
    cerrada = df.iloc[-2] 
    previas = df.iloc[-80:-2] # Historial para buscar los primeros 2 toques
    
    # 1. IDENTIFICAR ABANICO PERFECTO (Sobre la vela cerrada)
    tipo_tendencia = None
    if cerrada['ema30'] > cerrada['ema50'] > cerrada['ema100']: tipo_tendencia = "BUY"
    elif cerrada['ema30'] < cerrada['ema50'] < cerrada['ema100']: tipo_tendencia = "SELL"
    
    if not tipo_tendencia: return

    # 2. ESCANEO DEL HISTORIAL (Buscando 2 toques previos separados)
    toques_historial = 0
    tocando_actualmente = False
    
    for i in range(len(previas)):
        v = previas.iloc[i]
        margen_v = v['ema30'] * 0.0002 # Margen de cercanía del 0.02%
        
        if tipo_tendencia == "BUY":
            # Si toca la EMA 50, se arruina el historial. Conteo a cero.
            if v['low'] <= v['ema50']: 
                toques_historial = 0
                tocando_actualmente = False
                continue
            
            # Lógica de separación de toques a la EMA 30
            if v['low'] <= (v['ema30'] + margen_v): 
                if not tocando_actualmente: # Si no venía tocando, cuenta como toque NUEVO
                    toques_historial += 1
                    tocando_actualmente = True
            else:
                tocando_actualmente = False # Se despegó de la EMA 30
                
        elif tipo_tendencia == "SELL":
            # Si toca la EMA 50, se arruina el historial. Conteo a cero.
            if v['high'] >= v['ema50']: 
                toques_historial = 0
                tocando_actualmente = False
                continue
            
            # Lógica de separación de toques a la EMA 30
            if v['high'] >= (v['ema30'] - margen_v):
                if not tocando_actualmente:
                    toques_historial += 1
                    tocando_actualmente = True
            else:
                tocando_actualmente = False

    # 3. GATILLO FINAL AL CIERRE DE VELA
    margen_cierre = cerrada['ema30'] * 0.0002
    disparo = False
    
    if tipo_tendencia == "BUY":
        # Evaluamos que la vela cerrada tocó la 30, pero respetó la 50.
        if cerrada['low'] <= (cerrada['ema30'] + margen_cierre) and cerrada['low'] > cerrada['ema50']:
            # Tiene que ser un toque NUEVO (no una continuación de velas pegadas anteriores)
            if not tocando_actualmente:
                disparo = True

    elif tipo_tendencia == "SELL":
        if cerrada['high'] >= (cerrada['ema30'] - margen_cierre) and cerrada['high'] < cerrada['ema50']:
            if not tocando_actualmente:
                disparo = True

    # COMPROBACIÓN FINAL: ¿El gatillo actual es el 3ER TOQUE EXACTO?
    if disparo and toques_historial == 2:
        # ID de alerta basado en la vela cerrada para no duplicar NUNCA la alerta
        alerta_id = f"{clave}_{cerrada['epoch']}"
        if alerta_id in alertas_enviadas: return
        
        # Filtro de seguridad B/C
        if ("Crash" in nombre and tipo_tendencia == "BUY") or ("Boom" in nombre and tipo_tendencia == "SELL"): return

        mapa = await obtener_mapa_confluencia(ws, api_id)
        
        msg = (f"🎯 **SEÑAL VELA CERRADA: EMA 30 y 50** 🎯\n\n"
               f"📊 *Mercado:* `{nombre}`\n"
               f"⏱️ *TF:* `{tf_n}`\n"
               f"🔥 *Acción:* **{'🔴 VENTA' if tipo_tendencia == 'SELL' else '🟢 COMPRA'}**\n"
               f"✅ *Estructura:* **3er Toque EMA 30 (Al Cierre)**\n"
               f"🛡️ *Filtro:* EMA 50 Intacta\n\n"
               f"🌍 **MAPA DE ABANICOS:**\n{mapa}\n"
               f"📍 *Precio de Cierre:* `{round(cerrada['close'], 5)}`")
        
        enviar_telegram(msg)
        alertas_enviadas[alerta_id] = True

async def loop_principal():
    uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nom, sid in SIMBOLOS_API.items():
                        for tn, tv in TFS_SCAN.items():
                            await analizar_estrategia(ws, nom, sid, tn, tv)
                            await asyncio.sleep(0.15) 
                    await asyncio.sleep(15) 
        except: await asyncio.sleep(5)

async def main():
    enviar_telegram("🚀 **Bot 'Ema 30 y 50' V11.0 Online**\nModo: Gatillo de Vela Cerrada (15M-1D).\n_Buscando 3er Toque con Abanico Perfecto._")
    await loop_principal()

if __name__ == "__main__":
    asyncio.run(main())
