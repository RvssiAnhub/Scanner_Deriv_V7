import asyncio
import websockets
import json
import pandas as pd
import pandas_ta as ta
import requests
from datetime import datetime

# =============================================================
# 1. CONFIGURACIÓN QUIRÚRGICA 
# =============================================================
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'
APP_ID = '1089'  

TF_M5 = 300 # Temporalidad estricta M5

MERCADOS = {
    "Boom 1000 Index": "BOOM1000", "Boom 900 Index": "BOOM900", "Boom 600 Index": "BOOM600", "Boom 500 Index": "BOOM500", "Boom 300 Index": "BOOM300",
    "Crash 1000 Index": "CRASH1000", "Crash 900 Index": "CRASH900", "Crash 600 Index": "CRASH600", "Crash 500 Index": "CRASH500", "Crash 300 Index": "CRASH300"
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

async def pedir_velas(ws, sid, count=50):
    req = {"ticks_history": sid, "count": count, "end": "latest", "style": "candles", "granularity": TF_M5}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data and data["candles"]:
        df = pd.DataFrame(data["candles"])
        for c in ['close', 'high', 'low', 'open']: df[c] = df[c].astype(float)
        return df
    return None

# =============================================================
# 3. MATRIZ LÓGICA V14.0: CUALQUIER RETROCESO (23.6%)
# =============================================================
async def analizar_fibo_dinamico(ws, nombre, sid):
    global alertas_enviadas
    df = await pedir_velas(ws, sid)
    if df is None or len(df) < 40: return

    actual = df.iloc[-1]
    
    # ID de alerta para evitar spam en la misma vela de 5 minutos
    alerta_id = f"{sid}_{actual['epoch']}"
    if alerta_id in alertas_enviadas: return

    # 1. TRAZO DE FIBONACCI REACTIVO (Micro y Macro)
    # Usamos una ventana corta (25 velas) para atrapar CUALQUIER impulso y su retroceso
    ventana_dinamica = df.iloc[-25:-1] 
    historial_high = ventana_dinamica['high'].max()
    historial_low = ventana_dinamica['low'].min()
    distancia = historial_high - historial_low
    
    if distancia <= 0: return

    disparo = False
    es_boom = "Boom" in nombre
    
    # Lógica Matemática Fibo 23.6%
    if es_boom:
        nivel_236 = historial_low + (distancia * 0.236)
        # Margen del 0.05% para asegurar que se tome en cuenta si pasa "rozando"
        margen = nivel_236 * 0.0005 
        if actual['high'] >= (nivel_236 - margen): disparo = True
    else:
        nivel_236 = historial_high - (distancia * 0.236)
        margen = nivel_236 * 0.0005
        if actual['low'] <= (nivel_236 + margen): disparo = True

    # 2. GATILLO Y LECTURA TÉCNICA
    if disparo:
        alertas_enviadas[alerta_id] = True
        
        # Lectura de indicadores (Informativo)
        stoch_df = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3, smooth_k=3)
        val_k = stoch_df.iloc[-1]['STOCHk_14_3_3']
        val_d = stoch_df.iloc[-1]['STOCHd_14_3_3']
        val_cci = ta.cci(df['high'], df['low'], df['close'], length=14).iloc[-1]
        
        estado = ""
        if es_boom:
            estado = "🔴 SOBREVENTA DETECTADA" if (val_k < 20 or val_cci < -100) else "⚪ Zona Neutra"
        else:
            estado = "🟢 SOBRECOMPRA DETECTADA" if (val_k > 80 or val_cci > 100) else "⚪ Zona Neutra"

        msg = (f"⚡ **NUEVO RETROCESO FIBO 23.6%** ⚡\n\n"
               f"📊 *Mercado:* `{nombre}` | TF: `M5`\n"
               f"🎯 *Acción:* **{'🟢 COMPRA' if es_boom else '🔴 VENTA'}**\n\n"
               f"📏 *Nivel Fibonacci 23.6%:* `{round(nivel_236, 5)}`\n"
               f"📍 *Precio Actual:* `{round(actual['high'] if es_boom else actual['low'], 5)}`\n"
               f"───────────────────\n"
               f"🔍 **INFO TÉCNICA:**\n"
               f"📢 Estado: `{estado}`\n"
               f"📉 Stoch (14,3,3): `K:{round(val_k,1)} D:{round(val_d,1)}`\n"
               f"📈 CCI (14): `{round(val_cci,1)}`\n"
               f"───────────────────\n"
               f"⏰ _{datetime.now().strftime('%H:%M:%S UTC')}_")
        
        enviar_telegram(msg)

async def loop_principal():
    uri = "wss://ws.binaryws.com/websockets/v3?app_id=" + APP_ID
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nom, sid in MERCADOS.items():
                        await analizar_fibo_dinamico(ws, nom, sid)
                        await asyncio.sleep(0.1) # Extrema velocidad de escaneo
                    await asyncio.sleep(10) # Repite el ciclo M5 rápidamente
        except Exception as e:
            await asyncio.sleep(3) # Reconexión rápida

if __name__ == "__main__":
    enviar_telegram("⚡ **Scanner Fibo 23.6% Ultra Ligero (V14.0) ACTIVADO** ⚡\n_Modo Reactivo: Analizando cualquier retroceso en M5 sin gráficos para máxima velocidad._")
    asyncio.run(loop_principal())
