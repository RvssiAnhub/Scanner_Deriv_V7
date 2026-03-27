import asyncio
import websockets
import json
import pandas as pd
import requests
from datetime import datetime

# --- CONFIGURACIÓN DE IDENTIDAD ---
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'
APP_ID = '1089'

alertas_enviadas = {}

# --- LISTADO COMPLETO DE MERCADOS ---
SIMBOLOS_API = {
    "Boom 1000": "BOOM1000", "Boom 900": "BOOM900", "Boom 600": "BOOM600", "Boom 500": "BOOM500", "Boom 300": "BOOM300",
    "Crash 1000": "CRASH1000", "Crash 900": "CRASH900", "Crash 600": "CRASH600", "Crash 500": "CRASH500", "Crash 300": "CRASH300",
    "Vol 10": "R_10", "Vol 25": "R_25", "Vol 50": "R_50", "Vol 75": "R_75", "Vol 100": "R_100",
    "Vol 10(1s)": "1HZ10V", "Vol 25(1s)": "1HZ25V", "Vol 50(1s)": "1HZ50V", "Vol 75(1s)": "1HZ75V", "Vol 100(1s)": "1HZ100V",
    "Jump 10": "JD10", "Jump 25": "JD25", "Jump 50": "JD50", "Jump 75": "JD75", "Jump 100": "JD100",
    "Step": "stpRNG", "Step 200": "STEP200", "Step 500": "STEP500", "DEX 900 UP": "DEX900UP", "DEX 900 DN": "DEX900DN",
    "XAUUSD": "frxXAUUSD", "BTCUSD": "cryBTCUSD", "US Tech 100": "OTC_US100", "Wall Street 30": "OTC_US30"
}

# --- TEMPORALIDADES (Desde 1M hasta 4H) ---
TFS_SCAN = {"1M": 60, "5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}

def enviar_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except: pass

async def pedir_velas(ws, api_id, tf_sec, count=150):
    req = {"ticks_history": api_id, "count": count, "end": "latest", "style": "candles", "granularity": tf_sec}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data:
        df = pd.DataFrame(data["candles"])
        for c in ['close', 'high', 'low']: df[c] = df[c].astype(float)
        return df
    return None

async def analizar_fibo_inteligente(ws, nombre, api_id, tf_n, tf_v):
    global alertas_enviadas
    clave = f"FIBO_{nombre}_{tf_n}"
    
    df = await pedir_velas(ws, api_id, tf_v, 100)
    if df is None or len(df) < 60: return

    # 1. IDENTIFICAR ESTRUCTURA (Fractales de 5 velas)
    df['pico'] = df['high'][(df['high'] == df['high'].rolling(5, center=True).max())]
    df['valle'] = df['low'][(df['low'] == df['low'].rolling(5, center=True).min())]
    
    picos_validos = df.dropna(subset=['pico'])
    valles_validos = df.dropna(subset=['valle'])
    
    if len(picos_validos) < 1 or len(valles_validos) < 1: return
    
    ultimo_pico = picos_validos.iloc[-1]
    ultimo_valle = valles_validos.iloc[-1]
    
    # 2. DEFINIR DIRECCIÓN DEL MOVIMIENTO
    # Si el valle es anterior al pico -> Movimiento Alcista (Buscamos Retroceso para COMPRAR)
    # Si el pico es anterior al valle -> Movimiento Bajista (Buscamos Retroceso para VENDER)
    es_alcista = ultimo_valle.name < ultimo_pico.name
    distancia = abs(ultimo_pico['high'] - ultimo_valle['low'])
    
    # Nivel 61.8 Fibonacci
    if es_alcista:
        fibo_618 = ultimo_pico['high'] - (distancia * 0.618)
        tipo = "🟢 COMPRA (Retroceso)"
    else:
        fibo_618 = ultimo_valle['low'] + (distancia * 0.618)
        tipo = "🔴 VENTA (Retroceso)"

    # 3. GATILLO: VELA CERRADA CON RECHAZO
    cerrada = df.iloc[-2]
    actual = df.iloc[-1]
    margen = distancia * 0.05 # Margen de "proximidad" inteligente
    
    confirmado = False
    if es_alcista:
        # La vela cerrada pinchó el nivel 61.8 (o estuvo muy cerca) y cerró arriba
        if cerrada['low'] <= (fibo_618 + margen) and cerrada['close'] > fibo_618:
            confirmado = True
    else:
        # La vela cerrada pinchó el nivel 61.8 y cerró abajo
        if cerrada['high'] >= (fibo_618 - margen) and cerrada['close'] < fibo_618:
            confirmado = True

    if confirmado:
        alerta_id = f"{clave}_{cerrada['epoch']}"
        if alerta_id in alertas_enviadas: return
        
        # Filtro de seguridad para B/C
        if ("Crash" in nombre and "COMPRA" in tipo) or ("Boom" in nombre and "VENTA" in tipo): return

        msg = (f"📐 **FIBONACCI 61.8 DETECTADO** 📐\n\n"
               f"📊 *Mercado:* `{nombre}`\n"
               f"⏱️ *TF:* `{tf_n}`\n"
               f"🔥 *Acción:* **{tipo}**\n\n"
               f"📏 *Nivel Fibo:* `{round(fibo_618, 5)}`\n"
               f"📉 *Estructura:* {'Máximos más altos' if es_alcista else 'Mínimos más bajos'}\n"
               f"✅ *Gatillo:* **Rechazo al Cierre Confirmado**\n\n"
               f"📍 *Precio Actual:* `{actual['close']}`")
        
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
                            await analizar_fibo_inteligente(ws, nom, sid, tn, tv)
                            await asyncio.sleep(0.1) # Rapidez para 1M
                    await asyncio.sleep(10)
        except: await asyncio.sleep(5)

async def main():
    enviar_telegram("📐 **Bot Fibo 61.8 V12.0 Online**\nEscaneando desde 1M hasta 4H.\n_Estructura y Rechazo al Cierre Activos._")
    await loop_principal()

if __name__ == "__main__":
    asyncio.run(main())
