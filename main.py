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

# --- TEMPORALIDADES ESTRICTAS (1H, 4H, 1D) ---
TFS_SCAN = {"1H": 3600, "4H": 14400, "1D": 86400}

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
    
    # Pedimos 150 velas (suficiente para ver la tendencia macro en 1H/4H/1D)
    df = await pedir_velas(ws, api_id, tf_v, 150)
    if df is None or len(df) < 120: return

    # Cálculo exacto de EMAs
    df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
    
    actual = df.iloc[-1]
    
    # 1. IDENTIFICAR ABANICO Y TENDENCIA CLARA ACTUAL
    tipo_tendencia = None
    if actual['ema30'] > actual['ema50'] > actual['ema100']: tipo_tendencia = "BUY"
    elif actual['ema30'] < actual['ema50'] < actual['ema100']: tipo_tendencia = "SELL"
    
    if not tipo_tendencia: return

    # 2. ESCANEO DEL HISTORIAL PARA CONTEO DE TOQUES SEPARADOS
    # Analizamos las últimas 80 velas antes de la actual para encontrar la estructura
    previas = df.iloc[-80:-1]
    
    toques_completados = 0
    en_toque_ema30 = False
    
    for i in range(len(previas)):
        v = previas.iloc[i]
        
        if tipo_tendencia == "BUY":
            # REGLA DE ORO: Si toca la EMA 50, se invalida TODO el conteo previo
            if v['low'] <= v['ema50']: 
                toques_completados = 0
                en_toque_ema30 = False
                continue
            
            # Lógica de separación de toques a la EMA 30
            if v['low'] <= v['ema30']: 
                if not en_toque_ema30:
                    en_toque_ema30 = True # Entra en la zona del toque
            elif v['low'] > v['ema30']: 
                if en_toque_ema30:
                    toques_completados += 1 # Termina el toque, suma 1
                    en_toque_ema30 = False
                    
        elif tipo_tendencia == "SELL":
            # REGLA DE ORO: Si toca la EMA 50, se invalida TODO el conteo previo
            if v['high'] >= v['ema50']: 
                toques_completados = 0
                en_toque_ema30 = False
                continue
            
            # Lógica de separación de toques a la EMA 30
            if v['high'] >= v['ema30']:
                if not en_toque_ema30:
                    en_toque_ema30 = True
            elif v['high'] < v['ema30']:
                if en_toque_ema30:
                    toques_completados += 1
                    en_toque_ema30 = False

    # 3. GATILLO INMEDIATO (3ER TOQUE EXACTO EN VIVO)
    margen = actual['ema30'] * 0.0001
    disparo = False
    
    # Validamos que la vela actual esté tocando la EMA 30 (con margen) pero ESTRICTAMENTE sin tocar la 50
    if tipo_tendencia == "BUY" and actual['low'] <= (actual['ema30'] + margen) and actual['low'] > actual['ema50']: 
        disparo = True
    elif tipo_tendencia == "SELL" and actual['high'] >= (actual['ema30'] - margen) and actual['high'] < actual['ema50']: 
        disparo = True

    # Solo disparamos si el historial tiene EXACTAMENTE 2 toques previos completados
    if disparo and toques_completados == 2:
        alerta_id = f"{clave}_{actual['epoch']}"
        if alerta_id in alertas_enviadas: return
        
        # Filtro de seguridad (no operar spikes en contra)
        if ("Crash" in nombre and tipo_tendencia == "BUY") or ("Boom" in nombre and tipo_tendencia == "SELL"): return

        mapa = await obtener_mapa_confluencia(ws, api_id)
        
        msg = (f"🎯 **SEÑAL MACRO: EMA 30 y 50** 🎯\n\n"
               f"📊 *Mercado:* `{nombre}`\n"
               f"⏱️ *TF:* `{tf_n}`\n"
               f"🔥 *Acción:* **{'🔴 VENTA' if tipo_tendencia == 'SELL' else '🟢 COMPRA'}**\n"
               f"✅ *Estructura:* **3er Toque EMA 30 Confirmado**\n"
               f"🛡️ *Filtro:* EMA 50 Intacta\n\n"
               f"🌍 **MAPA DE ABANICOS (1H-4H-1D):**\n{mapa}\n"
               f"📍 *Precio:* `{round(actual['ema30'], 5)}`")
        
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
                    await asyncio.sleep(30) # En TF altos, podemos relajar el ciclo a 30 seg
        except: await asyncio.sleep(5)

async def main():
    enviar_telegram("🚀 **Bot 'Ema 30 y 50' MACRO Online**\nEscaneando estrictamente 1H, 4H y 1D.\n_Regla de 3 Toques y Abanico Perfecto Activada._")
    await loop_principal()

if __name__ == "__main__":
    asyncio.run(main())
