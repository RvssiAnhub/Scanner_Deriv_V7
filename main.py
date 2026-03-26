import os
import time
import json
import websocket
import pandas as pd
import pandas_ta as ta
import telebot
from datetime import datetime

# =============================================================
# 1. CONFIGURACIÓN DE PODER
# =============================================================
TOKEN = "8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E"
CHAT_ID = "8236681412"
bot = telebot.TeleBot(TOKEN)

# Parámetros Técnicos Quirúrgicos
EMA_R = 30  # Blanca (Reacción)
EMA_L = 50  # Azul (Base)
VELAS_TENDENCIA = 5 # Cuántas velas deben confirmar la tendencia previa al cruce
MARGEN_PROXIMIDAD = 0.0002 # 0.02% de margen para el toque (ajustable)

TFS_OPERATIVOS = ["5", "15", "30", "60", "240"] 
MERCADOS = {
    "Vol 10": "R_10", "Vol 25": "R_25", "Vol 50": "R_50", "Vol 75": "R_75", "Vol 100": "R_100",
    "Vol 10 (1s)": "1HZ10V", "Vol 25 (1s)": "1HZ25V", "Vol 50 (1s)": "1HZ50V", "Vol 75 (1s)": "1HZ75V", "Vol 100 (1s)": "1HZ100V",
    "Boom 1000": "BOOM1000", "Boom 500": "BOOM500", "Boom 300": "BOOM300",
    "Crash 1000": "CRASH1000", "Crash 500": "CRASH500", "Crash 300": "CRASH300",
    "Jump 10": "JD10", "Jump 25": "JD25", "Jump 50": "JD50", "Jump 75": "JD75", "Jump 100": "JD100",
    "DEX 600 UP": "DEXUP600", "DEX 600 DN": "DEXDN600", "DEX 900 UP": "DEXUP900", "DEX 900 DN": "DEXDN900",
    "Step Index": "stpRNG", "XAUUSD": "frxXAUUSD", "BTCUSD": "cryBTCUSD"
}

registros_alertas = {}

# =============================================================
# 2. MOTOR DE DATOS
# =============================================================
def obtener_datos(simbolo, tf, count=80):
    granuralidad = {"1": 60, "5": 300, "15": 900, "30": 1800, "60": 3600, "240": 14400, "1440": 86400}.get(str(tf))
    req = {"ticks_history": simbolo, "count": count, "end": "latest", "style": "candles", "granularity": granuralidad}
    try:
        ws = websocket.create_connection("wss://ws.binaryws.com/websockets/v3?app_id=1089", timeout=8)
        ws.send(json.dumps(req))
        res = json.loads(ws.recv())
        ws.close()
        if "candles" in res:
            df = pd.DataFrame(res["candles"])
            for col in ['open', 'high', 'low', 'close']: df[col] = df[col].astype(float)
            df['time'] = pd.to_datetime(df['epoch'], unit='s')
            return df
    except: return None

def obtener_macro(id_deriv):
    tfs = {"1M": "1", "5M": "5", "15M": "15", "1H": "60", "1D": "1440"}
    res = []
    for n, t in tfs.items():
        df = obtener_datos(id_deriv, t, count=60)
        if df is not None:
            df.ta.ema(length=EMA_R, append=True); df.ta.ema(length=EMA_L, append=True)
            ult = df.iloc[-1]
            icon = "🟢" if ult[f"EMA_{EMA_R}"] > ult[f"EMA_{EMA_L}"] else "🔴"
            res.append(f"{n}:{icon}")
    return " | ".join(res)

# =============================================================
# 3. LÓGICA QUIRÚRGICA V7.9
# =============================================================
def analizar(nombre, id_deriv, tf):
    df = obtener_datos(id_deriv, tf)
    if df is None or len(df) < 60: return

    df.ta.ema(length=EMA_R, append=True)
    df.ta.ema(length=EMA_L, append=True)
    
    c_r, c_l = f"EMA_{EMA_R}", f"EMA_{EMA_L}"
    actual = df.iloc[-1]
    
    # ID único para no repetir alerta en la misma vela
    alerta_id = f"{id_deriv}_{tf}_{actual['epoch']}"
    if alerta_id in registros_alertas: return

    # 1. VERIFICAR TENDENCIA PREVIA (5 velas antes del cruce)
    # Buscamos si hubo un cruce en las últimas 3 velas
    ventana_cruces = df.iloc[-4:-1]
    hubo_cruce_alcista = (ventana_cruces[c_r] <= ventana_cruces[c_l]).any() and actual[c_r] > actual[c_l]
    hubo_cruce_bajista = (ventana_cruces[c_r] >= ventana_cruces[c_l]).any() and actual[c_r] < actual[c_l]

    # 2. CALCULAR MÁRGENES DE PROXIMIDAD
    margen_arriba = actual[c_r] * (1 + MARGEN_PROXIMIDAD)
    margen_abajo = actual[c_r] * (1 - MARGEN_PROXIMIDAD)

    señal = None

    # ESTRATEGIA COMPRA 🟢
    if hubo_cruce_alcista:
        # Si el punto más bajo de la vela está en la zona de la EMA 30 (con margen)
        if actual['low'] <= margen_arriba:
            señal = "🟢 COMPRA"

    # ESTRATEGIA VENTA 🔴
    elif hubo_cruce_bajista:
        # Si el punto más alto de la vela está en la zona de la EMA 30 (con margen)
        if actual['high'] >= margen_abajo:
            señal = "🔴 VENTA"

    if señal:
        registros_alertas[alerta_id] = True
        macro = obtener_macro(id_deriv)
        tf_txt = f"M{tf}" if int(tf) < 60 else ("H1" if tf=="60" else "H4")
        
        msg = (f"🎯 **SEÑAL V7.9 DETECTADA**\n\n"
               f"🌐 **Mercado:** `{nombre}`\n"
               f"⚡ **Acción:** **{señal}**\n"
               f"⏱️ **Temporalidad:** `{tf_txt}`\n"
               f"📍 **Zona EMA 30:** `{round(actual[c_r], 5)}` (Margen Incluido)\n"
               f"───────────────────\n"
               f"📊 **Tendencias Macro (1M-1D):**\n"
               f"`{macro}`\n"
               f"───────────────────\n"
               f"⚠️ _Entrada detectada al toque inmediato._")
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

# =============================================================
# 4. BUCLE DE ALTA VELOCIDAD
# =============================================================
def main():
    print("🚀 Bot V7.9 Cirujano - Iniciado")
    try: bot.send_message(CHAT_ID, "✅ **V7.9 Online**\nEstrategia: Tendencia + Cruce + Margen de Proximidad.\n_Escaneo de alta frecuencia activo._", parse_mode="Markdown")
    except: pass

    while True:
        for nombre, sid in MERCADOS.items():
            for tf in TFS_OPERATIVOS:
                analizar(nombre, sid, tf)
                time.sleep(0.15) # Escaneo ultra-rápido entre mercados
        time.sleep(5) # Solo 5 segundos de descanso entre ciclos

if __name__ == "__main__":
    main()
