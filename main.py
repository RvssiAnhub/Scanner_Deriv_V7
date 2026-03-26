import os
import time
import json
import websocket
import pandas as pd
import pandas_ta as ta
import telebot
from datetime import datetime

# ==========================================
# CONFIGURACIÓN (ESTO NO CAMBIA)
# ==========================================
TOKEN = os.getenv("TELEGRAM_TOKEN", "8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E")
CHAT_ID = os.getenv("CHAT_ID", "8236681412")
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

TFS_OPERATIVOS = ["5", "15", "60"] # M5, M15 y H1

# ==========================================
# PARÁMETROS DE ESTRATEGIA (AJUSTADOS)
# ==========================================
EMA_RAPIDA = 30 # Blanca
EMA_LENTA = 50  # Azul
MIN_VELAS_PARALELAS = 8 # Rigor reducido de 15 a 8 velas de tendencia previa clara
registros_señales = {}

def obtener_historial_deriv(symbol, timeframe_minutes, count=100):
    g_segundos = {"5": 300, "15": 900, "60": 3600}.get(timeframe_minutes)
    req = {"ticks_history": symbol, "count": count, "end": "latest", "style": "candles", "granularity": g_segundos}
    try:
        ws = websocket.create_connection("wss://ws.binaryws.com/websockets/v3?app_id=1089", timeout=10)
        ws.send(json.dumps(req))
        result = json.loads(ws.recv())
        ws.close()
        if "candles" in result:
            df = pd.DataFrame(result["candles"])
            df['timestamp'] = pd.to_datetime(df['epoch'], unit='s')
            for col in ['open', 'high', 'low', 'close']: df[col] = df[col].astype(float)
            return df
    except: return None

def analizar_mercado(symbol_name, symbol_id, timeframe):
    df = obtener_historial_deriv(symbol_id, timeframe)
    if df is None: return
    
    df.ta.ema(length=EMA_RAPIDA, append=True)
    df.ta.ema(length=EMA_LENTA, append=True)
    
    c_ema_r = f"EMA_{EMA_RAPIDA}"
    c_ema_l = f"EMA_{EMA_LENTA}"
    
    if len(df) < 60: return

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    
    # ID único para no repetir alertas en la misma vela
    signal_id = f"{symbol_id}_{timeframe}_{curr['timestamp']}"
    if signal_id in registros_señales: return

    # --- LÓGICA DE PARALELISMO Y TENDENCIA CLARA ---
    # Miramos las últimas 8 velas ANTES del cruce
    lookback = df.iloc[-(MIN_VELAS_PARALELAS + 2) : -2]
    
    # ¿Venía de una tendencia bajista clara y paralela?
    venia_de_bajista = (lookback[c_ema_r] < lookback[c_ema_l]).all()
    
    # ¿Venía de una tendencia alcista clara y paralela?
    venia_de_alcista = (lookback[c_ema_r] > lookback[c_ema_l]).all()

    señal = None
    # CASO COMPRA: Venía bajista -> Cruza al alza -> Precio toca EMA 30
    if venia_de_bajista and curr[c_ema_r] > curr[c_ema_l]:
        if curr['low'] <= curr[c_ema_r] and curr['close'] > curr[c_ema_r]:
            señal = "COMPRA 🔵 (Cruce tras tendencia clara)"

    # CASO VENTA: Venía alcista -> Cruza a la baja -> Precio toca EMA 30
    elif venia_de_alcista and curr[c_ema_r] < curr[c_ema_l]:
        if curr['high'] >= curr[c_ema_r] and curr['close'] < curr[c_ema_r]:
            señal = "VENTA 🔴 (Cruce tras tendencia clara)"

    if señal:
        registros_señales[signal_id] = True
        msg = (f"🚀 **NUEVA SEÑAL DETECTADA**\n"
               f"Mercado: `{symbol_name}`\n"
               f"TF: `M{timeframe}`\n"
               f"Acción: **{señal}**\n"
               f"Entrada sugerida: `{round(curr[c_ema_r], 5)}`")
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

def main():
    print("🤖 Scanner Iniciado con Lógica de EMAs Paralelas (API 1089)")
    while True:
        for name, sid in MERCADOS.items():
            for tf in TFS_OPERATIVOS:
                analizar_mercado(name, sid, tf)
                time.sleep(0.3)
        time.sleep(60)

if __name__ == "__main__":
    main()
