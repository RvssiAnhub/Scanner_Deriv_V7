import os
import time
import json
import websocket
import pandas as pd
import pandas_ta as ta
import telebot
from datetime import datetime

# =============================================================
# 1. CREDENCIALES (VERIFICADAS)
# =============================================================
TOKEN = "8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E"
CHAT_ID = "8236681412"
bot = telebot.TeleBot(TOKEN)

MERCADOS = {
    "Vol 10": "R_10", "Vol 25": "R_25", "Vol 50": "R_50", "Vol 75": "R_75", "Vol 100": "R_100",
    "Vol 10 (1s)": "1HZ10V", "Vol 25 (1s)": "1HZ25V", "Vol 50 (1s)": "1HZ50V", "Vol 75 (1s)": "1HZ75V", "Vol 100 (1s)": "1HZ100V",
    "Boom 1000": "BOOM1000", "Boom 500": "BOOM500", "Boom 300": "BOOM300",
    "Crash 1000": "CRASH1000", "Crash 500": "CRASH500", "Crash 300": "CRASH300",
    "Jump 10": "JD10", "Jump 25": "JD25", "Jump 50": "JD50", "Jump 75": "JD75", "Jump 100": "JD100",
    "DEX 600 UP": "DEXUP600", "DEX 600 DN": "DEXDN600", "DEX 900 UP": "DEXUP900", "DEX 900 DN": "DEXDN900",
    "Step Index": "stpRNG", "XAUUSD": "frxXAUUSD", "BTCUSD": "cryBTCUSD"
}

EMA_R = 30  # Blanca
EMA_L = 50  # Azul
VELAS_PARALELAS = 8 
TFS = ["5", "15", "60"]
registros_alertas = {}

# =============================================================
# 2. MOTOR DE DATOS Y ESTRATEGIA
# =============================================================
def obtener_datos_deriv(simbolo, tf, count=100):
    segundos = {"5": 300, "15": 900, "60": 3600}.get(tf)
    req = {"ticks_history": simbolo, "count": count, "end": "latest", "style": "candles", "granularity": segundos}
    try:
        ws = websocket.create_connection("wss://ws.binaryws.com/websockets/v3?app_id=1089", timeout=10)
        ws.send(json.dumps(req))
        resultado = json.loads(ws.recv())
        ws.close()
        if "candles" in resultado:
            df = pd.DataFrame(resultado["candles"])
            df['time'] = pd.to_datetime(df['epoch'], unit='s')
            for col in ['open', 'high', 'low', 'close']: df[col] = df[col].astype(float)
            return df
    except: return None

def analizar(nombre, id_deriv, tf):
    df = obtener_datos_deriv(id_deriv, tf)
    if df is None or len(df) < 60: return

    df.ta.ema(length=EMA_R, append=True)
    df.ta.ema(length=EMA_L, append=True)
    
    col_r, col_l = f"EMA_{EMA_R}", f"EMA_{EMA_L}"
    actual = df.iloc[-1]
    
    # Evitar repeticiones
    alerta_id = f"{id_deriv}_{tf}_{actual['time']}"
    if alerta_id in registros_alertas: return

    # Lógica de Paralelismo (8 velas previas)
    ventana = df.iloc[-(VELAS_PARALELAS + 2) : -2]
    bajista_limpia = (ventana[col_r] < ventana[col_l]).all()
    alcista_limpia = (ventana[col_r] > ventana[col_l]).all()

    señal = None
    # COMPRA: Venía bajista -> Cruza arriba -> Toca EMA 30
    if bajista_limpia and actual[col_r] > actual[col_l]:
        if actual['low'] <= actual[col_r] and actual['close'] > actual[col_r]:
            señal = "🔵 COMPRA (Setup V7.5)"

    # VENTA: Venía alcista -> Cruza abajo -> Toca EMA 30
    elif alcista_limpia and actual[col_r] < actual[col_l]:
        if actual['high'] >= actual[col_r] and actual['close'] < actual[col_r]:
            señal = "🔴 VENTA (Setup V7.5)"

    if señal:
        registros_alertas[alerta_id] = True
        msg = (f"🎯 **SEÑAL V7.5.1 DETECTADA**\n\n"
               f"📈 Mercado: `{nombre}`\n"
               f"⏰ TF: `M{tf}`\n"
               f"⚡ Acción: **{señal}**\n"
               f"📍 Punto de Entrada: `{round(actual[col_r], 5)}`")
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

# =============================================================
# 3. BUCLE PRINCIPAL (CON MENSAJE DE ARRANQUE)
# =============================================================
def main():
    print("🚀 Iniciando Bot V7.5.1...")
    try:
        # MENSAJE DE CONFIRMACIÓN INMEDIATA
        bot.send_message(CHAT_ID, "✅ **Bot V7.5.1 Operativo**\nEstrategia: 8 Velas Paralelas + Toque EMA 30.\n_Escaneando mercados en tiempo real..._", parse_mode="Markdown")
    except Exception as e:
        print(f"Error al enviar mensaje inicial: {e}")

    while True:
        for nombre, sid in MERCADOS.items():
            for tf in TFS:
                analizar(nombre, sid, tf)
                time.sleep(0.4) 
        print(f"Ronda completada a las {datetime.now().strftime('%H:%M:%S')}. Todo OK.")
        time.sleep(60)

if __name__ == "__main__":
    main()
