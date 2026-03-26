import os
import time
import json
import websocket
import pandas as pd
import pandas_ta as ta
import telebot
from datetime import datetime

# =============================================================
# 1. CONFIGURACIÓN DE CONEXIÓN Y NOTIFICACIONES
# =============================================================
# Credenciales integradas para Railway y API 1089 de Deriv
TOKEN = "8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E"
CHAT_ID = "8236681412"
bot = telebot.TeleBot(TOKEN)

# Diccionario completo de activos monitoreados
MERCADOS = {
    "Vol 10": "R_10", "Vol 25": "R_25", "Vol 50": "R_50", "Vol 75": "R_75", "Vol 100": "R_100",
    "Vol 10 (1s)": "1HZ10V", "Vol 25 (1s)": "1HZ25V", "Vol 50 (1s)": "1HZ50V", "Vol 75 (1s)": "1HZ75V", "Vol 100 (1s)": "1HZ100V",
    "Boom 1000": "BOOM1000", "Boom 500": "BOOM500", "Boom 300": "BOOM300",
    "Crash 1000": "CRASH1000", "Crash 500": "CRASH500", "Crash 300": "CRASH300",
    "Jump 10": "JD10", "Jump 25": "JD25", "Jump 50": "JD50", "Jump 75": "JD75", "Jump 100": "JD100",
    "DEX 600 UP": "DEXUP600", "DEX 600 DN": "DEXDN600", "DEX 900 UP": "DEXUP900", "DEX 900 DN": "DEXDN900",
    "Step Index": "stpRNG", "XAUUSD": "frxXAUUSD", "BTCUSD": "cryBTCUSD"
}

# =============================================================
# 2. PARÁMETROS DE ESTRATEGIA QUIRÚRGICA V7.5
# =============================================================
EMA_R = 30  # Blanca (Línea de reacción y Pullback)
EMA_L = 50  # Azul (Tendencia de fondo)
VELAS_PARALELAS = 8 # Rigor: 8 velas previas con EMAs separadas
TFS = ["5", "15", "60"] # Temporalidades de escaneo
registros_alertas = {}

def obtener_datos_deriv(simbolo, tf, count=100):
    # Traducir temporalidad a segundos para la API
    segundos = {"5": 300, "15": 900, "60": 3600}.get(tf)
    req = {
        "ticks_history": simbolo,
        "count": count,
        "end": "latest",
        "style": "candles",
        "granularity": segundos
    }
    try:
        ws = websocket.create_connection("wss://ws.binaryws.com/websockets/v3?app_id=1089", timeout=10)
        ws.send(json.dumps(req))
        resultado = json.loads(ws.recv())
        ws.close()
        if "candles" in resultado:
            df = pd.DataFrame(resultado["candles"])
            df['time'] = pd.to_datetime(df['epoch'], unit='s')
            for col in ['open', 'high', 'low', 'close']:
                df[col] = df[col].astype(float)
            return df
    except Exception as e:
        return None

def ejecutar_estrategia_paralela(nombre, id_deriv, tf):
    df = obtener_datos_deriv(id_deriv, tf)
    if df is None or len(df) < 60: return

    # Cálculo exacto de indicadores
    df.ta.ema(length=EMA_R, append=True)
    df.ta.ema(length=EMA_L, append=True)
    
    col_rapida = f"EMA_{EMA_R}"
    col_lenta = f"EMA_{EMA_L}"
    
    actual = df.iloc[-1]
    
    # Identificador único para evitar spam en la misma vela
    alerta_id = f"{id_deriv}_{tf}_{actual['time']}"
    if alerta_id in registros_alertas: return

    # --- LÓGICA DE TENDENCIA PREVIA PARALELA ---
    # Analizamos las 8 velas anteriores al posible cruce (excluyendo la actual)
    ventana_previa = df.iloc[-(VELAS_PARALELAS + 2) : -2]
    
    # Verificación de paralelismo: EMAs deben estar ordenadas y sin tocarse
    previa_bajista_limpia = (ventana_previa[col_rapida] < ventana_previa[col_lenta]).all()
    previa_alcista_limpia = (ventana_previa[col_rapida] > ventana_previa[col_lenta]).all()

    señal = None
    
    # ESCENARIO COMPRA: Tendencia bajista clara -> Cruce al alza -> Pullback a la EMA 30
    if previa_bajista_limpia and actual[col_rapida] > actual[col_lenta]:
        if actual['low'] <= actual[col_rapida] and actual['close'] > actual[col_rapida]:
            señal = "🔵 COMPRA (Cruce + Paralelismo)"

    # ESCENARIO VENTA: Tendencia alcista clara -> Cruce a la baja -> Pullback a la EMA 30
    elif previa_alcista_limpia and actual[col_rapida] < actual[col_lenta]:
        if actual['high'] >= actual[col_rapida] and actual['close'] < actual[col_rapida]:
            señal = "🔴 VENTA (Cruce + Paralelismo)"

    # --- ENVÍO DE NOTIFICACIÓN ---
    if señal:
        registros_alertas[alerta_id] = True
        mensaje = (f"🎯 **SEÑAL V7.5 DETECTADA**\n\n"
                   f"📈 Mercado: `{nombre}`\n"
                   f"⏰ TF: `M{tf}`\n"
                   f"⚡ Acción: **{señal}**\n"
                   f"📍 Punto de Entrada: `{round(actual[col_rapida], 5)}`")
        bot.send_message(CHAT_ID, mensaje, parse_mode="Markdown")

def main():
    print("🤖 Bot V7.5 (Estrategia Paralela) - Iniciado y Monitorizando API 1089...")
    while True:
        for nombre, sid in MERCADOS.items():
            for tf in TFS:
                ejecutar_estrategia_paralela(nombre, sid, tf)
                time.sleep(0.3) # Delay de seguridad para la API
        time.sleep(60) # Espera un minuto antes del siguiente ciclo completo

if __name__ == "__main__":
    main()
