import os
import time
import json
import websocket
import pandas as pd
import pandas_ta as ta
import telebot
from datetime import datetime

# ==========================================
# CONFIGURACIÓN DE ENTORNO
# ==========================================
TOKEN = os.getenv("TELEGRAM_TOKEN", "8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E")
CHAT_ID = os.getenv("CHAT_ID", "8236681412")
bot = telebot.TeleBot(TOKEN)

# ==========================================
# DICCIONARIO DE MERCADOS DERIV (Extraído de tus imágenes)
# ==========================================
MERCADOS = {
    # Volatility Indices
    "Vol 10": "R_10", "Vol 25": "R_25", "Vol 50": "R_50", "Vol 75": "R_75", "Vol 100": "R_100",
    "Vol 10 (1s)": "1HZ10V", "Vol 25 (1s)": "1HZ25V", "Vol 50 (1s)": "1HZ50V", "Vol 75 (1s)": "1HZ75V", "Vol 100 (1s)": "1HZ100V",
    "Vol 15": "R_15", "Vol 30": "R_30", "Vol 90": "R_90",
    # Crash & Boom
    "Boom 1000": "BOOM1000", "Boom 500": "BOOM500", "Boom 300": "BOOM300",
    "Crash 1000": "CRASH1000", "Crash 500": "CRASH500", "Crash 300": "CRASH300",
    # Jump Indices
    "Jump 10": "JD10", "Jump 25": "JD25", "Jump 50": "JD50", "Jump 75": "JD75", "Jump 100": "JD100",
    # Step & DEX
    "Step Index": "stpRNG", 
    "DEX 600 UP": "DEXUP600", "DEX 600 DOWN": "DEXDN600",
    "DEX 900 UP": "DEXUP900", "DEX 900 DOWN": "DEXDN900",
    "DEX 1500 UP": "DEXUP1500", "DEX 1500 DOWN": "DEXDN1500",
    # Metales y Cripto
    "XAUUSD": "frxXAUUSD", "XAGUSD": "frxXAGUSD", "BTCUSD": "cryBTCUSD"
}

# Temporalidades operativas (en minutos)
TFS_OPERATIVOS = ["5", "15", "60", "240"]

# Reglas de la Estrategia Pura
EMA_RAPIDA = 30
EMA_LENTA = 50
LOOKBACK_TENDENCIA_PREVIA = 25 
MIN_VELAS_CONDUCCION = 15      

registros_señales = {}

# ==========================================
# MOTOR WEB-SOCKET DERIV API (APP_ID 1089)
# ==========================================
def obtener_historial_deriv(symbol, timeframe_minutes, count=150):
    """Se conecta al corazón de Deriv vía WS para extraer velas exactas"""
    # Deriv requiere la granularidad en segundos exactos
    valid_granularities = {1: 60, 5: 300, 15: 900, 60: 3600, 240: 14400, 1440: 86400}
    g_segundos = valid_granularities.get(int(timeframe_minutes))
    
    if not g_segundos: return None

    req = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "start": 1,
        "style": "candles",
        "granularity": g_segundos
    }
    
    try:
        # Conexión directa al API de Deriv
        ws = websocket.create_connection("wss://ws.binaryws.com/websockets/v3?app_id=1089", timeout=10)
        ws.send(json.dumps(req))
        result = json.loads(ws.recv())
        ws.close()

        if "candles" in result and result["candles"]:
            df = pd.DataFrame(result["candles"])
            df['timestamp'] = pd.to_datetime(df['epoch'], unit='s')
            for col in ['open', 'high', 'low', 'close']:
                df[col] = df[col].astype(float)
            return df
        return None
    except Exception as e:
        # Silenciamos errores menores de desconexión para no ensuciar la consola
        return None

def calcular_indicadores(df):
    if df is None or len(df) < EMA_LENTA + LOOKBACK_TENDENCIA_PREVIA: return None
    df.ta.ema(length=EMA_RAPIDA, append=True)
    df.ta.ema(length=EMA_LENTA, append=True)
    return df

def get_trend_emoji(df):
    if df is None or len(df) < 2: return "⚪"
    df = calcular_indicadores(df)
    last = df.iloc[-1]
    return "🟢" if last[f"EMA_{EMA_RAPIDA}"] > last[f"EMA_{EMA_LENTA}"] else "🔴"

def generar_resumen_tendencias(symbol_id):
    resumen = ""
    for name, tf in {"1M": 1, "5M": 5, "15M": 15, "1H": 60, "1D": 1440}.items():
        df_res = obtener_historial_deriv(symbol_id, tf, count=EMA_LENTA + 5)
        emoji = get_trend_emoji(df_res)
        resumen += f"{name}: {emoji} | "
    return resumen[:-3]

# ==========================================
# LÓGICA DE ESTRATEGIA
# ==========================================
def analizar_mercado(symbol_name, symbol_id, timeframe):
    df = obtener_historial_deriv(symbol_id, timeframe, count=150)
    df = calcular_indicadores(df)
    if df is None: return

    c_ema_r = f"EMA_{EMA_RAPIDA}"
    c_ema_l = f"EMA_{EMA_LENTA}"
    current_candle = df.iloc[-1]
    prev_candle = df.iloc[-2]
    
    signal_id = f"{symbol_id}_{timeframe}_{current_candle['timestamp']}"
    if signal_id in registros_señales: return

    # FASE 1: FILTRO DE TENDENCIA PREVIA LARGA
    lookback_start = -(LOOKBACK_TENDENCIA_PREVIA + 3)
    lookback_end = -3
    df_previa = df.iloc[lookback_start : lookback_end]
    
    if len(df_previa) < LOOKBACK_TENDENCIA_PREVIA: return

    ema_r_previa = df_previa[c_ema_r]
    ema_l_previa = df_previa[c_ema_l]
    
    cond_alcista_previa = (
        (ema_r_previa > ema_l_previa).all() and 
        (df_previa['close'] > ema_l_previa).sum() >= MIN_VELAS_CONDUCCION
    )
    
    cond_bajista_previa = (
        (ema_r_previa < ema_l_previa).all() and 
        (df_previa['close'] < ema_l_previa).sum() >= MIN_VELAS_CONDUCCION
    )

    if not (cond_alcista_previa or cond_bajista_previa): return

    # FASE 2 Y 3: CRUCE Y RETESTEO
    señal = None
    
    # NUEVA TENDENCIA ALCISTA
    if cond_bajista_previa and current_candle[c_ema_r] > current_candle[c_ema_l]:
        cruce_confirmado = (prev_candle[c_ema_r] <= prev_candle[c_ema_l] or df.iloc[-3][c_ema_r] <= df.iloc[-3][c_ema_l])
        if cruce_confirmado:
            margen_toque = current_candle[c_ema_r] * 0.0001
            if current_candle['low'] <= (current_candle[c_ema_r] + margen_toque) and current_candle['close'] > (current_candle[c_ema_r] - margen_toque):
                señal = "COMPRA 🔵 (Setup Alcista)"

    # NUEVA TENDENCIA BAJISTA
    elif cond_alcista_previa and current_candle[c_ema_r] < current_candle[c_ema_l]:
        cruce_confirmado = (prev_candle[c_ema_r] >= prev_candle[c_ema_l] or df.iloc[-3][c_ema_r] >= df.iloc[-3][c_ema_l])
        if cruce_confirmado:
            margen_toque = current_candle[c_ema_r] * 0.0001
            if current_candle['high'] >= (current_candle[c_ema_r] - margen_toque) and current_candle['close'] < (current_candle[c_ema_r] + margen_toque):
                señal = "VENTA 🔴 (Setup Bajista)"

    # ENVÍO DE SEÑAL
    if señal:
        registros_señales[signal_id] = True
        if len(registros_señales) > 1000: registros_señales.pop(next(iter(registros_señales)))

        tf_v = int(timeframe)
        tf_txt = f"H{tf_v//60}" if tf_v >= 60 else f"M{tf_v}"
        resumen_trends = generar_resumen_tendencias(symbol_id)
        precio_entrada = round(current_candle[c_ema_r], 4)

        mensaje = (
            f"⚠️ **SEÑAL PROFESIONAL DE TRADING**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 **Mercado:** `{symbol_name}`\n"
            f"⏱️ **Timeframe:** `{tf_txt}`\n"
            f"🚦 **Acción:** *{señal}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔹 **Regla Confirmada:** Tendencia previa larga + Cruce + Reteste EMA{EMA_RAPIDA}\n\n"
            f"📍 **Precio de Entrada Exacto:**\n"
            f"`Entrada en: {precio_entrada} (Toque EMA {EMA_RAPIDA})`\n\n"
            f"🔍 **Resumen de tendencias:**\n"
            f"`{resumen_trends}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ _Generado: {datetime.now().strftime('%H:%M:%S UTC')}_"
        )
        
        try: bot.send_message(CHAT_ID, mensaje, parse_mode="Markdown")
        except: pass

# ==========================================
# BUCLE PRINCIPAL
# ==========================================
def main():
    print("🤖 Bot conectado vía WS App ID: 1089")
    print("Escaneando mercado ampliado...")
    bot.send_message(CHAT_ID, "✅ Bot de Señales Actualizado (API 1089) Iniciado y Monitorizando...")

    while True:
        for symbol_name, symbol_id in MERCADOS.items():
            print(f"Buscando en {symbol_name}...", end="\r")
            for tf in TFS_OPERATIVOS:
                analizar_mercado(symbol_name, symbol_id, tf)
                time.sleep(0.5) 
        
        print(f"\nRonda finalizada. Esperando 2 minutos... [{datetime.now().strftime('%H:%M:%S')}]")
        print("="*50)
        time.sleep(120)

if __name__ == "__main__":
    main()
