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
TFS = ["5", "15", "30", "60", "240"] # Escaneo operativo (M5 a H4)
registros_alertas = {}

# =============================================================
# 2. MOTOR DE DATOS (ACTUALIZADO PARA 1M Y 1D)
# =============================================================
def obtener_datos(simbolo, tf, count=80):
    segundos = {"1": 60, "5": 300, "15": 900, "30": 1800, "60": 3600, "240": 14400, "1440": 86400}.get(str(tf))
    req = {"ticks_history": simbolo, "count": count, "end": "latest", "style": "candles", "granularity": segundos}
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
# 3. GENERADOR DE RESUMEN DE TENDENCIAS MACRO
# =============================================================
def obtener_tendencias_macro(id_deriv):
    tfs_macro = {"1M": "1", "5M": "5", "15M": "15", "1H": "60", "1D": "1440"}
    resumen = []
    
    for nombre, tf in tfs_macro.items():
        df = obtener_datos(id_deriv, tf, count=60)
        if df is not None and len(df) >= 55:
            df.ta.ema(length=EMA_R, append=True)
            df.ta.ema(length=EMA_L, append=True)
            actual = df.iloc[-1]
            
            # 🟢 Alcista si EMA 30 > EMA 50 | 🔴 Bajista si EMA 30 < EMA 50
            if actual[f"EMA_{EMA_R}"] > actual[f"EMA_{EMA_L}"]:
                resumen.append(f"{nombre}: 🟢")
            else:
                resumen.append(f"{nombre}: 🔴")
        else:
            resumen.append(f"{nombre}: ⚪")
            
    return " | ".join(resumen)

# =============================================================
# 4. LÓGICA V7.8: GATILLO INMEDIATO AL TOQUE
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

    # 🟢 COMPRA: Hubo cruce alcista reciente Y el precio actual tocó/cruzó la EMA 30 hacia abajo
    if (previa[c_r] <= previa[c_l] and actual[c_r] > actual[c_l]) or (df.iloc[-3][c_r] <= df.iloc[-3][c_l] and actual[c_r] > actual[c_l]):
        if actual['low'] <= actual[c_r]: # GATILLO: Apenas la mecha o el cuerpo toca la EMA 30
            señal = "🟢 COMPRA"

    # 🔴 VENTA: Hubo cruce bajista reciente Y el precio actual tocó/cruzó la EMA 30 hacia arriba
    elif (previa[c_r] >= previa[c_l] and actual[c_r] < actual[c_l]) or (df.iloc[-3][c_r] >= df.iloc[-3][c_l] and actual[c_r] < actual[c_l]):
        if actual['high'] >= actual[c_r]: # GATILLO: Apenas la mecha o el cuerpo toca la EMA 30
            señal = "🔴 VENTA"

    if señal:
        registros_alertas[alerta_id] = True
        
        # Obtenemos el mapa macro solo cuando hay señal para no saturar la API
        resumen_tendencias = obtener_tendencias_macro(id_deriv)
        tf_label = f"M{tf}" if int(tf) < 60 else (f"H1" if tf == "60" else "H4")
        
        msg = (f"⚡ **SEÑAL V7.8 (TOQUE INMEDIATO)** ⚡\n\n"
               f"🌐 **Mercado:** `{nombre}`\n"
               f"🎯 **Acción:** **{señal}**\n"
               f"⏱️ **TF Señal:** `{tf_label}`\n"
               f"📍 **Entrada (Toque EMA 30):** `{round(actual[c_r], 5)}`\n"
               f"───────────────────\n"
               f"📊 **Resumen de Tendencias (EMA 30 vs 50):**\n"
               f"`{resumen_tendencias}`\n"
               f"───────────────────\n"
               f"⚠️ _Evaluación manual requerida._")
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

# =============================================================
# 5. BUCLE DE ESCANEO
# =============================================================
def main():
    print("🚀 Bot V7.8 - Iniciado (Gatillo al toque + Macro)")
    try:
        bot.send_message(CHAT_ID, "✅ **Bot V7.8 Operativo**\nModo: Francotirador (Alerta inmediata al toque de EMA 30).\n_Incluye mapa de tendencias 1M-1D._", parse_mode="Markdown")
    except: pass

    while True:
        for nombre, sid in MERCADOS.items():
            for tf in TFS:
                analizar_mercado(nombre, sid, tf)
                time.sleep(0.3)
        time.sleep(25) # Escaneo rápido

if __name__ == "__main__":
    main()
