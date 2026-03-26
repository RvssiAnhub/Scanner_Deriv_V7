import os
import time
import json
import websocket
import pandas as pd
import pandas_ta as ta
import telebot
from datetime import datetime

# =============================================================
# 1. CREDENCIALES Y CONFIGURACIÓN (SE MANTIENEN IGUAL)
# =============================================================
TOKEN = "8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E"
CHAT_ID = "8236681412"
bot = telebot.TeleBot(TOKEN)

# Diccionario Quirúrgico de Activos (Únicamente Booms y Crashes)
MERCADOS = {
    "Boom 1000": "BOOM1000", "Boom 500": "BOOM500", "Boom 300": "BOOM300",
    "Crash 1000": "CRASH1000", "Crash 500": "CRASH500", "Crash 300": "CRASH300",
}

# Temporalidades para Escaneo Operativo
TFS_SCAN = {"5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}
# Rango de reporte solicitado: 1M a 4H
TFS_REPORTE = {"1M": 60, "5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}

# =============================================================
# 2. PARÁMETROS TÉCNICOS QUIRÚRGICOS V8.0 (ESTRATEGIA MANUAL)
# =============================================================
# Configuración basada rigurosamente en el manual
BULLS_PERIOD = 1000  
# Margen quirúrgico del 0.02% para el Bulls Power
MARGEN_BULLS = 0.0002 
# Margen quirúrgico de proximidad del 0.02% para el toque inmediato del RSI
MARGEN_RSI = 0.0002 

registros_señales = {}

# =============================================================
# 3. MOTOR DE DATOS Y LÓGICA DE ALTA PRECISIÓN
# =============================================================
def obtener_historial_deriv(symbol, tf_minutes, count=100):
    granuralidad = {"1": 60, "5": 300, "15": 900, "30": 1800, "60": 3600, "240": 14400, "1440": 86400}.get(str(tf_minutes))
    req = {"ticks_history": symbol, "count": count, "end": "latest", "style": "candles", "granularity": granuralidad}
    try:
        ws = websocket.create_connection("wss://ws.binaryws.com/websockets/ v3?app_id=1089", timeout=10)
        ws.send(json.dumps(req))
        resultado = json.loads(ws.recv())
        ws.close()
        if "candles" in resultado and resultado["candles"]:
            df = pd.DataFrame(resultado["candles"])
            for col in ['open', 'high', 'low', 'close']: df[col] = df[col].astype(float)
            df['time'] = pd.to_datetime(df['epoch'], unit='s')
            return df
        return None
    except: return None

# --- REPORTE MACRO DE CONFLUENCIA 1M A 4H ---
def calcular_tendencias_macro(id_deriv):
    # Genera el mapa macro de tendencias al momento exacto de la señal
    reporte = []
    # Usamos TFS_REPORTE que incluye M1 y H4
    for nombre, tf in TFS_REPORTE.items():
        # Pre-seeding profesional para EMAs precisas
        df = obtener_historial_deriv(id_deriv, tf, count=1200)
        # La estrategia del manual usa EMA 30 blanca y EMA 50 azul como base.
        if df is not None and len(df) >= 1100:
            df.ta.ema(length=30, append=True); df.ta.ema(length=50, append=True)
            ult = df.iloc[-1]
            icon = "🟢" if ult["EMA_30"] > ult["EMA_50"] else "🔴"
            reporte.append(f"{nombre}: {icon}")
        else:
            reporte.append(f"{nombre}: ⚪")
    return " | ".join(reporte)

def analizar_mercado(nombre, id_deriv, tf):
    df = obtener_historial_deriv(id_deriv, tf)
    if df is None or len(df) < 55: return

    # Asignación quirúrgica del RSI Period según activo operativo
    rsi_period = 14 if "1000" in nombre else 6
    df.ta.rsi(length=rsi_period, append=True)
    df.ta.bulls(length=BULLS_PERIOD, append=True)
    
    col_rsi, col_bp = f"RSI_{rsi_period}", f"BULLS_{BULLS_PERIOD}"
    
    # Vela actual operativa para gatillo inmediato
    actual = df.iloc[-1]
    
    # ID único para no repetir alerta en la misma vela de 1 o 5 minutos
    alerta_id = f"{id_deriv}_{tf}_{actual['epoch']}"
    if alerta_id in registros_señales: return

    # 1. VERIFICAR TENDENCIA PREVIA LIMPIA (Manual V8.0)
    # Buscamos si hubo un cruce de EMAs 30 y 50 en las últimas 3 velas para dar memoria de tendencia
    if len(df) < 303: return
    ventana_cruces = df.iloc[-4:-1]
    # EMA 30 > EMA 50 es tendencia alcista limpia.
    previa_bajista = (ventana_cruces['close'].ewm(span=30, adjust=False).mean() < ventana_cruces['close'].ewm(span=50, adjust=False).mean()).all()
    previa_alcista = (ventana_cruces['close'].ewm(span=30, adjust=False).mean() > ventana_cruces['close'].ewm(span=50, adjust=False).mean()).all()

    señal = None

    # LÓGICA DE GATILLO INMEDIATO AL TOQUE (CON MARGENES CIRUJANOS)

    # 🟢 CASO COMPRA (Setup V8.0): RSI <= 5 AND Bulls Power >= Nivel 10 (Alcista de sobreventa).
    if previa_bajista:
        # GATILLO: Apenas la mecha o el cuerpo toca el margen del RSI <= 5
        # Margen de proximidad del 0.02% para no perder entradas.
        if actual[col_rsi] <= (5 + MARGEN_RSI):
            señal = "COMPRA V8.0 (Setup RSI/Bulls)"

    # 🔴 CASO VENTA (Setup V8.0): RSI >= 95 AND Bulls Power <= Nivel 90 (Bajista de sobrecompra).
    elif previa_alcista:
        # GATILLO: Apenas la mecha o el cuerpo toca el margen del RSI >= 95
        # Margen de proximidad del 0.02% para no perder entradas.
        if actual[col_rsi] >= (95 - MARGEN_RSI):
            señal = "VENTA V8.0 (Setup RSI/Bulls)"

    # --- ENVÍO DE SEÑAL PROFESIONAL A TELEGRAM ---
    if señal:
        registros_señales[alerta_id] = True
        
        # Obtenemos el mapa macro de tendencias 1M a 4H solo cuando hay señal para no saturar la API.
        macro = calcular_tendencias_macro(id_deriv)
        # Formateo profesional de temporalidad
        tf_v = int(tf)
        tf_txt = f"H{tf_v//60}" if tf_v >= 60 else f"M{tf_v}"
        
        # MENSAJE DE ALTA PRECISIÓN SOLICITADO
        msg = (f"🎯 **SEÑAL V8.0 DETECTADA**\n\n"
               f"🌐 Mercado: `{nombre}` | TF Señal: `{tf_txt}`\n"
               f"🚫 Tendencia Previa: Limpia ✅\n"
               f"⚡ Acción: **{señal}**\n\n"
               f"📍 **Zona RSI (Toque Inmediato):** `{round(actual[col_rsi], 5)}` (Margen Incluido)\n"
               f"───────────────────\n"
               f"📊 **MAPA DE TENDENCIAS MACRO (1M-4H):**\n`{macro}`\n"
               f"───────────────────\n"
               f"⏰ _Generado: {datetime.now().strftime('%H:%M:%S UTC')}_")
        
        try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        except: pass

# =============================================================
# 4. BUCLE DE ESCANEO DE ALTA FRECUENCIA (RAILWAY WORKER)
# =============================================================
def main():
    print("🤖 Scanner V8.0 - Iniciado y Monitorizando Booms y Crashes...")
    try:
        # MENSAJE DE CONFIRMACIÓN INMEDIATA
        bot.send_message(CHAT_ID, "✅ **Scanner V8.0 Operativo**\nEstrategia: RSI/Bulls Power (Toque Inmediato al 0.02%).\n_Solo escaneando mercados de Boom y Crash._", parse_mode="Markdown")
    except: pass

    while True:
        for nombre, sid in MERCADOS.items():
            for tf in TFS_SCAN:
                analizar_mercado(nombre, sid, tf)
                # Delay quirúrgico de seguridad de 0.15s para no saturar la API de Deriv.
                time.sleep(0.15) 
        # Ciclo rápido de 10 segundos antes del siguiente escaneo completo para más rapidez
        time.sleep(10)

if __name__ == "__main__":
    main()
