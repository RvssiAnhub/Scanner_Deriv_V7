import os
import time
import json
import websocket
import pandas as pd
import pandas_ta as ta
import telebot
from datetime import datetime

# =============================================================
# 1. CREDENCIALES Y CONFIGURACIÓN
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
TFS = ["5", "15", "60"]
registros_alertas = {}

# =============================================================
# 2. MOTOR DE DATOS
# =============================================================
def obtener_datos(simbolo, tf):
    segundos = {"5": 300, "15": 900, "60": 3600}.get(tf)
    req = {"ticks_history": simbolo, "count": 100, "end": "latest", "style": "candles", "granularity": segundos}
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
# 3. LÓGICA V7.6: CRUCE + TOQUE (SIN FILTRO DE VELAS PREVIAS)
# =============================================================
def analizar_v76(nombre, id_deriv, tf):
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

    # ESTRATEGIA: Cruce de las 2 EMAs + Toque del precio a la EMA 30
    
    # 🔵 POSIBLE COMPRA: Cruce alcista (Blanca cruza arriba de Azul)
    if previa[c_r] <= previa[c_l] and actual[c_r] > actual[c_l]:
        # El precio debe tocar o estar cerca de la EMA 30 (Pullback)
        if actual['low'] <= actual[c_r]:
            señal = "🔵 COMPRA (Cruce V7.6)"

    # 🔴 POSIBLE VENTA: Cruce bajista (Blanca cruza abajo de Azul)
    elif previa[c_r] >= previa[c_l] and actual[c_r] < actual[c_l]:
        # El precio debe tocar o estar cerca de la EMA 30 (Pullback)
        if actual['high'] >= actual[c_r]:
            señal = "🔴 VENTA (Cruce V7.6)"

    if señal:
        registros_alertas[alerta_id] = True
        msg = (f"⚡ **SEÑAL V7.6 DETECTADA**\n\n"
               f"Mercado: `{nombre}` | TF: `M{tf}`\n"
               f"Acción: **{señal}**\n"
               f"Precio EMA 30: `{round(actual[c_r], 5)}`")
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

# =============================================================
# 4. BUCLE DE ESCANEO
# =============================================================
def main():
    print("🚀 Bot V7.6 Cruce Dinámico - Iniciado")
    try:
        bot.send_message(CHAT_ID, "✅ **Bot V7.6 Activo**\nLógica: Cruce Directo de EMAs + Pullback.\n_Escaneando mercados..._", parse_mode="Markdown")
    except: pass

    while True:
        for nombre, sid in MERCADOS.items():
            for tf in TFS:
                analizar_v76(nombre, sid, tf)
                time.sleep(0.3)
        print(f"Ciclo completado: {datetime.now().strftime('%H:%M:%S')}")
        time.sleep(30) # Reducimos descanso a 30 segundos para más rapidez

if __name__ == "__main__":
    main()
