import asyncio
import websockets
import json
import pandas as pd
import requests
from telegram.ext import Application, MessageHandler, filters

# --- CONFIGURACIÓN ---
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
APP_ID = '1089'
CHAT_ID = '8236681412'

senales_enviadas = {}

SIMBOLOS = {
    "Boom 1000": "BOOM1000", "Boom 500": "BOOM500", "Crash 1000": "CRASH1000", "Crash 500": "CRASH500",
    "Vol 10 (1s)": "1HZ10V", "Vol 50 (1s)": "1HZ50V", "Vol 75 (1s)": "1HZ75V", "Vol 100 (1s)": "1HZ100V",
    "Step Index": "stpRNG", "BTCUSD": "cryBTCUSD"
}

# Temporalidades a escanear para entradas (Pullbacks)
TFS_SCAN = {"5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}

# --- FUNCIONES AUXILIARES ---
async def pedir_datos(ws, api, tf, cant=100):
    req = {"ticks_history": api, "count": cant, "end": "latest", "style": "candles", "granularity": tf}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data:
        df = pd.DataFrame(data["candles"])
        df['close'] = df['close'].astype(float)
        df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        return df
    return None

async def obtener_tendencia(ws, api, tf):
    df = await pedir_datos(ws, api, tf, 60)
    if df is None: return "⚪"
    return "🟢" if df['ema30'].iloc[-1] > df['ema50'].iloc[-1] else "🔴"

# --- LÓGICA DEL ESCÁNER V9.0 ---
async def escanear():
    uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nom, api in SIMBOLOS.items():
                        # Primero chequeamos tendencias maestras una sola vez por activo
                        t1h = await obtener_tendencia(ws, api, 3600)
                        t4h = await obtener_tendencia(ws, api, 14400)

                        for tf_nom, tf_val in TFS_SCAN.items():
                            df = await pedir_datos(ws, api, tf_val)
                            if df is None: continue
                            
                            ultimo = df.iloc[-1]
                            # Dirección del cruce actual en el TF que estamos viendo
                            dir_actual = "BUY" if ultimo['ema30'] > ultimo['ema50'] else "SELL"
                            
                            # --- REGLAS DE ALINEACIÓN V9.0 ---
                            autorizado = False
                            
                            if tf_nom in ["5M", "15M", "30M"]:
                                # Estas requieren alineación con 1H Y 4H
                                if dir_actual == "BUY" and t1h == "🟢" and t4h == "🟢": autorizado = True
                                if dir_actual == "SELL" and t1h == "🔴" and t4h == "🔴": autorizado = True
                                
                            elif tf_nom == "1H":
                                # La de 1H solo requiere estar alineada con la mayor (4H)
                                if (dir_actual == "BUY" and t4h == "🟢") or (dir_actual == "SELL" and t4h == "🔴"):
                                    autorizado = True
                                    
                            elif tf_nom == "4H":
                                # Si hay cruce y pullback en 4H, se manda directo (es la tendencia máxima)
                                autorizado = True

                            # --- DETECCIÓN DE PULLBACK ---
                            # El precio debe estar muy cerca de la EMA 30 (0.015% de distancia)
                            distancia = abs(ultimo['close'] - ultimo['ema30']) / ultimo['close']
                            
                            if autorizado and distancia < 0.00015:
                                clave = f"{nom}_{tf_nom}_{dir_actual}"
                                if clave not in senales_enviadas:
                                    emoji = "💎" if tf_nom in ["1H", "4H"] else "🛡️"
                                    txt_alerta = (
                                        f"{emoji} *SEÑAL DETECTADA V9.0* {emoji}\n\n"
                                        f"📊 *Activo:* `{nom}`\n"
                                        f"⏱️ *Temporalidad:* {tf_nom}\n"
                                        f"🔥 *Acción:* {'🔵 COMPRA' if dir_actual == 'BUY' else '🔴 VENTA'}\n"
                                        f"💰 *Precio:* `{round(ultimo['close'], 5)}`\n\n"
                                        f"🌍 *Filtros:* H1:{t1h} | H4:{t4h}"
                                    )
                                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                                                 json={"chat_id": CHAT_ID, "text": txt_alerta, "parse_mode": "Markdown"})
                                    senales_enviadas[clave] = True
                    
                    await asyncio.sleep(30) # Respiro para no saturar la API
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(10)

async def main():
    print("Iniciando Scanner V9.0...")
    # Mensaje de bienvenida al bot
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                 json={"chat_id": CHAT_ID, "text": "🚀 *Scanner V9.0 Online*\n✅ Escaneando 5M, 15M, 30M (alineados)\n✅ Escaneando 1H y 4H (directos/alineados)", "parse_mode": "Markdown"})
    await escanear()

if __name__ == "__main__":
    asyncio.run(main())
