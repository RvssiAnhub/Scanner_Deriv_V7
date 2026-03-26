import os
import time
import json
import websocket
import pandas as pd
import pandas_ta as ta
import telebot
from datetime import datetime

# =============================================================
# 1. CREDENCIALES
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
# AHORA SÍ ESCANEA DE 5M A 4H
TFS = ["5", "15", "30", "60", "240"] 
registros_alertas = {}

# =============================================================
# 2. MOTOR DE DATOS
# =============================================================
def obtener_datos(simbolo, tf):
    # Traducción exacta de minutos a segundos para Deriv
    segundos = {"5": 300, "15": 900, "30": 1800, "60": 3600, "240": 14400}.get(tf)
    req = {"ticks_history": simbolo, "count": 80, "end": "latest", "style": "candles", "granularity": segundos}
    try:
        ws = websocket.create_connection("wss://ws.binaryws.com/websockets/v3?app_id=1089", timeout=10)
        ws.send(json.dumps(req))
        res = json.loads(ws.recv())
        ws.close()
        if "candles" in res:
            df = pd.DataFrame(res["candles"])
            df['time'] = pd.to_datetime(df['epoch'], unit='s')
            for col in ['open', 'high', 'low', 'close']: df[col] = df[col].astype(float)
            return df
    except: return None

# =============================================================
# 3. LÓGICA V7.7: CRUCE SEGURO + PULLBACK
# =============================================================
def analizar_mercado(nombre, id_deriv, tf):
    df = obtener_datos(id_deriv, tf)
    if df is None or len(df) < 55: return

    df.ta.ema(length=EMA_R, append=True)
    df.ta.ema(length=EMA_L, append=True)
    
    c_r, c_l = f"EMA_{EMA_R}", f"EMA_{EMA_L}"
    actual = df.iloc[-1]
    previa = df.iloc[-2]
    
    alerta_id = f"{id_deriv}_{tf}_{actual['time']}"
    if alerta_id in registros_alertas: return

    señal = None

    # COMPRA: Cruce alcista + Toque + Cierre FIRME por encima de la EMA 30
    if previa[c_r] <= previa[c_l] and actual[c_r] > actual[c_l]:
        if actual['low'] <= actual[c_r] and actual['close'] > actual[c_r]:
            # Evita señales falsas si la vela es roja y cierra débil
            if actual['close'] > actual['open']: 
                señal = "🟢 COMPRA"

    # VENTA: Cruce bajista + Toque + Cierre FIRME por debajo de la EMA 30
    elif previa[c_r] >= previa[c_l] and actual[c_r] < actual[c_l]:
        if actual['high'] >= actual[c_r] and actual['close'] < actual[c_r]:
            # Evita señales falsas si la vela es verde y cierra débil
            if actual['close'] < actual['open']: 
                señal = "🔴 VENTA"

    if señal:
        registros_alertas[alerta_id] = True
        
        # Etiqueta visual para la temporalidad
        tf_label = f"M{tf}" if int(tf) < 60 else (f"H1" if tf == "60" else "H4")
        
        # MENSAJE CON FORMATO PROFESIONAL
        msg = (f"⚡ **NUEVA SEÑAL DETECTADA** ⚡\n\n"
               f"🌐 **Mercado:** `{nombre}`\n"
               f"🎯 **Acción:** **{señal}**\n"
               f"⏱️ **Temporalidad de la Señal:** `{tf_label}`\n"
               f"📍 **Nivel de Entrada (EMA 30):** `{round(actual[c_r], 5)}`\n"
               f"───────────────────\n"
               f"📊 _Rango de escaneo activo:_ `[M5 - M15 - M30 - H1 - H4]`")
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

# =============================================================
# 4. BUCLE DE ESCANEO
# =============================================================
def main():
    print("🚀 Bot V7.7 - Iniciado")
    try:
        bot.send_message(CHAT_ID, "✅ **Bot V7.7 Operativo**\nEscaner de 5M a 4H activado.\n_Buscando cruces de tendencia..._", parse_mode="Markdown")
    except: pass

    while True:
        for nombre, sid in MERCADOS.items():
            for tf in TFS:
                analizar_mercado(nombre, sid, tf)
                time.sleep(0.3)
        time.sleep(30)

if __name__ == "__main__":
    main()
