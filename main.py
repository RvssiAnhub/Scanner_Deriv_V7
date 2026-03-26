import asyncio
import websockets
import json
import pandas as pd
import requests
from telegram.ext import Application, MessageHandler, filters

# --- CONFIGURACIÓN DE IDENTIDAD ---
APP_ID = '1089' 
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'

# Memorias de señales
senales_enviadas_cruces_precisos = {}
cruces_confirmados_estrategia_2_precisa = {} 

SIMBOLOS_API = {
    "Boom 1000 Index": "BOOM1000", "Boom 500 Index": "BOOM500", "Boom 300 Index": "BOOM300",
    "Crash 1000 Index": "CRASH1000", "Crash 500 Index": "CRASH500", "Crash 300 Index": "CRASH300",
    "Volatility 10 Index": "R_10", "Volatility 25 Index": "R_25", "Volatility 50 Index": "R_50", "Volatility 75 Index": "R_75", "Volatility 100 Index": "R_100",
    "Volatility 10 (1s) Index": "1HZ10V", "Volatility 25 (1s) Index": "1HZ25V", "Volatility 50 (1s) Index": "1HZ50V", "Volatility 75 (1s) Index": "1HZ75V", "Volatility 100 (1s) Index": "1HZ100V",
    "Jump 10 Index": "JD10", "Jump 25 Index": "JD25", "Jump 50 Index": "JD50", "Jump 75 Index": "JD75", "Jump 100 Index": "JD100", 
    "Step Index": "stpRNG", "BTCUSD": "cryBTCUSD", "ETHUSD": "cryETHUSD"
}

# Temporalidades para Escaneo
TFS_SCAN = {"5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}
# Rango de reporte solicitado: 1M a 4H
TFS_REPORTE = {"1M": 60, "5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}

def enviar_telegram_sync(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}, timeout=5)
    except: pass

async def pedir_velas(ws, simbolo_api, tf_segundos, cantidad):
    req = {"ticks_history": simbolo_api, "count": cantidad, "end": "latest", "style": "candles", "granularity": tf_segundos}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data:
        df = pd.DataFrame(data["candles"])
        for c in ['close', 'high', 'low']: df[c] = df[c].astype(float)
        return df
    return None

async def obtener_tendencia_tf(ws, simbolo_api, tf_v):
    df_t = await pedir_velas(ws, simbolo_api, tf_v, 80)
    if df_t is None or len(df_t) < 60: return "⚪"
    e30 = df_t['close'].ewm(span=30, adjust=False).mean().iloc[-1]
    e50 = df_t['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    return "🟢" if e30 > e50 else "🔴"

async def atender_mensaje_usuario(update, context):
    txt = update.message.text.lower()
    if "tendencias actuales" in txt:
        await update.message.reply_text("🔎 Analizando mercados (1M a 4H)...")
        uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
        reporte = "📊 *ESTADO ACTUAL (1M-4H)*\n\n"
        async with websockets.connect(uri) as ws:
            for nom, api in SIMBOLOS_API.items():
                linea = f"*{nom.split()[0]}:* "
                for n_tf, v_tf in TFS_REPORTE.items():
                    t = await obtener_tendencia_tf(ws, api, v_tf)
                    linea += f"{n_tf}{t} "
                reporte += linea + "\n"
                await asyncio.sleep(0.1)
        await update.message.reply_text(reporte, parse_mode="Markdown")

async def analizar_estrategia_cruce_pulback_precisa(ws, nombre_simbolo, simbolo_api, tf_n, tf_v):
    global cruces_confirmados_estrategia_2_precisa, senales_enviadas_cruces_precisos
    clave_base = f"{nombre_simbolo}_{tf_n}_pback_pro"
    
    df = await pedir_velas(ws, simbolo_api, tf_v, 500)
    if df is None or len(df) < 300: return
    
    df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # 1. Detección de Cruce Reciente
    i_cross, dir_cross = -1, None
    for i in range(len(df)-4, len(df)):
        v, p = df.iloc[i], df.iloc[i-1]
        if (v['ema30'] < v['ema50']) and not (p['ema30'] < p['ema50']): i_cross, dir_cross = i, "SELL"
        elif (v['ema30'] > v['ema50']) and not (p['ema30'] > v['ema50']): i_cross, dir_cross = i, "BUY"
    
    if i_cross == -1: return

    # 2. Gatillo Inmediato al Toque (Vela actual) con Margen 0.02%
    v_actual = df.iloc[-1]
    margen = v_actual['ema30'] * 0.0002
    
    disparo = False
    if dir_cross == "SELL" and v_actual['high'] >= (v_actual['ema30'] - margen): disparo = True
    elif dir_cross == "BUY" and v_actual['low'] <= (v_actual['ema30'] + margen): disparo = True

    if disparo:
        alerta_id = f"{clave_base}_{v_actual['epoch']}"
        if alerta_id in senales_enviadas_cruces_precisos: return
        
        # Filtro Boom/Crash
        if ("Crash" in nombre_simbolo and dir_cross == "BUY") or ("Boom" in nombre_simbolo and dir_cross == "SELL"): return

        # Generar Reporte 1M a 4H
        reporte_total = ""
        for n, val in TFS_REPORTE.items():
            tend = await obtener_tendencia_tf(ws, simbolo_api, val)
            reporte_total += f"• {n}: {tend}\n"

        msg = (f"🎯 *SEÑAL V7.9.2 (TOQUE INMEDIATO)* 🎯\n\n"
               f"📊 *Mercado:* `{nombre_simbolo}`\n"
               f"⏱️ *TF:* {tf_n}\n"
               f"🔥 *Acción:* {'🔴 VENTA' if dir_cross == 'SELL' else '🟢 COMPRA'}\n\n"
               f"🌍 *CONFLUENCIA (1M-4H):*\n{reporte_total}\n"
               f"📍 *Precio:* `{round(v_actual['ema30'], 5)}`")
        
        enviar_telegram_sync(msg)
        senales_enviadas_cruces_precisos[alerta_id] = True

async def loop_escaneo():
    uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nom, api in SIMBOLOS_API.items():
                        for n_tf, v_tf in TFS_SCAN.items():
                            await analizar_estrategia_cruce_pulback_precisa(ws, nom, api, n_tf, v_tf)
                            await asyncio.sleep(0.15)
                    await asyncio.sleep(10)
        except: await asyncio.sleep(5)

async def main():
    enviar_telegram_sync("🚀 Scanner V7.9.2 Online\nConfig: Toque + Mapa 1M-4H")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, atender_mensaje_usuario))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await loop_escaneo()

if __name__ == "__main__":
    asyncio.run(main())
