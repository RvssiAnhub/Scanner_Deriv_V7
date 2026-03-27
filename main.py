import asyncio
import websockets
import json
import pandas as pd
import requests
from telegram.ext import Application
import time
from datetime import datetime

# --- CONFIGURACIÓN DE IDENTIDAD ---
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'
APP_ID = '1089'

# Diccionario de Estados (Memoria de pullbacks para el 3er toque)
estado_toques = {} 
alertas_enviadas = {}

# --- LISTADO EXPANDIDO DE MERCADOS (DERIV COMPLETO) ---
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

TFS_SCAN = {"5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}
TFS_REPORTE = {"1M": 60, "5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}

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
    for n, v in TFS_REPORTE.items():
        df = await pedir_velas(ws, api_id, v, 120)
        if df is not None:
            e30 = df['close'].ewm(span=30, adjust=False).mean().iloc[-1]
            e50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
            e100 = df['close'].ewm(span=100, adjust=False).mean().iloc[-1]
            if e30 > e50 > e100: mapa += f"• {n}: 🟢\n"
            elif e30 < e50 < e100: mapa += f"• {n}: 🔴\n"
            else: mapa += f"• {n}: ⚪\n"
    return mapa

async def analizar_estrategia(ws, nombre, api_id, tf_n, tf_v):
    global estado_toques, alertas_enviadas
    clave = f"{nombre}_{tf_n}"
    
    df = await pedir_velas(ws, api_id, tf_v, 400)
    if df is None or len(df) < 350: return

    # Cálculo de EMAs
    df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
    
    actual = df.iloc[-1]
    previas = df.iloc[-60:-1] # Historial reciente para validar los 2 toques previos

    # --- REGLA 4: ALINEACIÓN PERFECTA ---
    tipo_tendencia = None
    if actual['close'] > actual['ema30'] > actual['ema50'] > actual['ema100']: tipo_tendencia = "BUY"
    elif actual['close'] < actual['ema30'] < actual['ema50'] < actual['ema100']: tipo_tendencia = "SELL"
    
    if not tipo_tendencia:
        estado_toques[clave] = 0 # Reset si se pierde la alineación
        return

    # --- CONTEO DE PULLBACKS (REGLAS 2 Y 3) ---
    # Validamos cuántas veces el precio tocó la EMA 30 sin haber tocado la EMA 50 antes de ahora
    toques_validos = 0
    en_zona_pullback = False
    
    for i in range(len(previas)):
        v = previas.iloc[i]
        if tipo_tendencia == "BUY":
            # Toque a EMA 30 pero no a EMA 50
            if v['low'] <= v['ema30'] and v['low'] > v['ema50']:
                if not en_zona_pullback:
                    toques_validos += 1
                    en_zona_pullback = True
            elif v['low'] > v['ema30']: en_zona_pullback = False
            if v['low'] <= v['ema50']: toques_validos = 0 # Invalida secuencia
        else: # SELL
            if v['high'] >= v['ema30'] and v['high'] < v['ema50']:
                if not en_zona_pullback:
                    toques_validos += 1
                    en_zona_pullback = True
            elif v['high'] < v['ema30']: en_zona_pullback = False
            if v['high'] >= v['ema50']: toques_validos = 0

    # --- GATILLO INMEDIATO (3ER TOQUE) CON MARGEN 0.01% ---
    margen = actual['ema30'] * 0.0001
    disparo = False
    
    if tipo_tendencia == "BUY" and actual['low'] <= (actual['ema30'] + margen): disparo = True
    elif tipo_tendencia == "SELL" and actual['high'] >= (actual['ema30'] - margen): disparo = True

    if disparo and toques_validos == 2:
        alerta_id = f"{clave}_{actual['epoch']}"
        if alerta_id in alertas_enviadas: return
        
        # Filtro de seguridad B/C
        if ("Crash" in nombre and tipo_tendencia == "BUY") or ("Boom" in nombre and tipo_tendencia == "SELL"): return

        mapa = await obtener_mapa_confluencia(ws, api_id)
        
        msg = (f"🎯 **SEÑAL Ema 30 y 50** 🎯\n\n"
               f"📊 Mercado: `{nombre}`\n"
               f"⏱️ TF Señal: `{tf_n}`\n"
               f"🔥 Acción: **{'🔴 VENTA' if tipo_tendencia == 'SELL' else '🟢 COMPRA'}**\n"
               f"✅ Conteo: **3er Pullback Confirmado**\n\n"
               f"🌍 **CONFLUENCIA (1M-4H):**\n{mapa}\n"
               f"📍 Precio: `{round(actual['ema30'], 5)}` (Toque Inmediato)")
        
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
                            await asyncio.sleep(0.1) # Respetar límites de API
                    await asyncio.sleep(5)
        except: await asyncio.sleep(5)

async def main():
    enviar_telegram("🚀 **Bot 'Ema 30 y 50' Online**\nEscaneando 5M-4H con Rigor Quirúrgico.\n_Portafolio Completo Activado._")
    await loop_principal()

if __name__ == "__main__":
    asyncio.run(main())
