import asyncio
import websockets
import json
import pandas as pd
import requests

# --- CONFIGURACIÓN CRÍTICA ---
APP_ID = '1089' 
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'

# Diccionarios de memoria para control de señales y cruces
senales_enviadas_cruces_precisos = {}
cruces_confirmados_estrategia_2_precisa = {} 

# --- MAPEO DE SÍMBOLOS (Nombres para Telegram -> Códigos Deriv API) ---
SIMBOLOS_API = {
    "Boom 1000 Index": "BOOM1000", "Boom 500 Index": "BOOM500", "Boom 300 Index": "BOOM300",
    "Crash 1000 Index": "CRASH1000", "Crash 500 Index": "CRASH500", "Crash 300 Index": "CRASH300",
    "Volatility 10 Index": "R_10", "Volatility 25 Index": "R_25", "Volatility 50 Index": "R_50", "Volatility 75 Index": "R_75", "Volatility 100 Index": "R_100",
    "Volatility 10 (1s) Index": "1HZ10V", "Volatility 25 (1s) Index": "1HZ25V", "Volatility 50 (1s) Index": "1HZ50V", "Volatility 75 (1s) Index": "1HZ75V", "Volatility 100 (1s) Index": "1HZ100V",
    "Jump 10 Index": "JD10", "Jump 25 Index": "JD25", "Jump 50 Index": "JD50", "Jump 75 Index": "JD75", "Jump 100 Index": "JD100", 
    "Step Index": "stpRNG", "BTCUSD": "cryBTCUSD", "ETHUSD": "cryETHUSD"
}

# Temporalidades solicitadas (M5 a 4H) en SEGUNDOS para Deriv API
TFS_SCAN_PRECISO = {
    "5M": 300, "15M": 900, "30M": 1800, 
    "1H": 3600, "4H": 14400
}

# Temporalidades para el Reporte Multi-TF completo en SEGUNDOS
TFS_REPORTE_FULL = {
    "1M": 60, "5M": 300, "15M": 900, 
    "30M": 1800, "1H": 3600, "4H": 14400
}

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: 
        requests.post(url, json={"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}, timeout=5)
    except: 
        print("❌ Error de comunicación con Telegram")

async def pedir_velas(ws, simbolo_api, tf_segundos, cantidad):
    req = {
        "ticks_history": simbolo_api,
        "adjust_start_time": 1,
        "count": cantidad,
        "end": "latest",
        "start": 1,
        "style": "candles",
        "granularity": tf_segundos
    }
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data and len(data["candles"]) > 0:
        df = pd.DataFrame(data["candles"])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        return df
    return None

async def obtener_tendencia_tf(ws, simbolo_api, tf_v):
    # Pedimos solo 80 velas para aligerar la carga, pero suficiente para EMAs
    df_t = await pedir_velas(ws, simbolo_api, tf_v, 80)
    if df_t is None or len(df_t) < 60: return "S/D ⚪"
    
    e30 = df_t['close'].ewm(span=30, adjust=False).mean().iloc[-1]
    e50 = df_t['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    
    if e30 > e50: return "UP 🟢"
    if e30 < e50: return "DOWN 🔴"
    return "RNG ⚖️"

async def analizar_estrategia_cruce_pulback_precisa(ws, nombre_simbolo, simbolo_api, tf_n, tf_v):
    global cruces_confirmados_estrategia_2_precisa, senales_enviadas_cruces_precisos
    clave_base = f"{nombre_simbolo}_{tf_n}_pback_pro"
    
    # Pedimos suficientes velas para ver el historial PRE-CRUCE (60+50+pullback+buffer)
    df = await pedir_velas(ws, simbolo_api, tf_v, 500)
    if df is None or len(df) < 300: return
    
    df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # 1. ENCONTRAR EL CRUCE MÁS RECIENTE
    i_cross, dir_cross = -1, None
    for i in range(len(df)-60, len(df)):
        v, p = df.iloc[i], df.iloc[i-1]
        if (v['ema30'] < v['ema50']) and not (p['ema30'] < p['ema50']): i_cross, dir_cross = i, "SELL"
        elif (v['ema30'] > v['ema50']) and not (p['ema30'] > v['ema50']): i_cross, dir_cross = i, "BUY"
    
    if i_cross == -1: return

    # 2. FILTRO DE TENDENCIA PREVIA "LARGA Y CLARA" (Lookback de 50 velas)
    trend_lookback = 50
    v_pre = df.iloc[i_cross - trend_lookback : i_cross]
    if dir_cross == "SELL":
        limpieza = (v_pre['ema30'] > v_pre['ema50']).sum()
        if limpieza < (trend_lookback * 0.8): return 
    else: # BUY
        limpieza = (v_pre['ema30'] < v_pre['ema50']).sum()
        if limpieza < (trend_lookback * 0.8): return

    # Registro de cruce confirmado
    if clave_base not in cruces_confirmados_estrategia_2_precisa or \
       cruces_confirmados_estrategia_2_precisa[clave_base]['index'] != i_cross:
        cruces_confirmados_estrategia_2_precisa[clave_base] = {'index': i_cross, 'direction': dir_cross}
        if clave_base in senales_enviadas_cruces_precisos: del senales_enviadas_cruces_precisos[clave_base]

    if clave_base in senales_enviadas_cruces_precisos: return

    # 3. VERIFICAR UN PUSH INICIAL Y EL RETEST (PULLBACK) PRECISO
    i_retest = -1
    for i in range(i_cross + 5, len(df)):
        v = df.iloc[i]
        margen = v['ema30'] * 0.00005 # Margen ultra-ajustado de precisión
        
        t_ok = False
        if dir_cross == "SELL":
            if v['high'] >= (v['ema30'] - margen): t_ok = True
        else: # BUY
            if v['low'] <= (v['ema30'] + margen): t_ok = True
        
        if t_ok:
            i_retest = i; break
    
    # 4. DISPARO DE SEÑAL EN LA VELAS RECIENTES
    if i_retest != -1 and (i_retest >= len(df) - 2):
        v_retest = df.iloc[i_retest]
        
        # Confirmamos cierre: No debe cerrar del lado equivocado de la EMA 50
        confirmation_close = False
        if dir_cross == "SELL":
            if v_retest['close'] < v_retest['ema50']: confirmation_close = True
        else: # BUY
            if v_retest['close'] > v_retest['ema50']: confirmation_close = True
            
        if confirmation_close:
            tipo = "🔴 VENTA" if dir_cross == "SELL" else "🔵 COMPRA"
            
            # Filtro de seguridad Boom/Crash
            if ("Crash" in nombre_simbolo and dir_cross == "BUY") or ("Boom" in nombre_simbolo and dir_cross == "SELL"): return

            # Construir reporte de confluencia FULL (1M-4H)
            reporte_total = ""
            for n, val in TFS_REPORTE_FULL.items():
                tendencia = await obtener_tendencia_tf(ws, simbolo_api, val)
                reporte_total += f"• {n}: {tendencia}\n"

            msg = (
                f"💎 *ALERTA: PULLBACK ULTRA-PRECISO* 💎\n\n"
                f"📊 *Mercado:* `{nombre_simbolo}`\n"
                f"⏱️ *TF:* {tf_n}\n"
                f"🚫 *Estado:* Tendencia Previa Larga Confirmada ✅\n"
                f"🎯 *Evento:* Toque Perfecto EMA 30 Confirmado\n"
                f"🔥 *Acción:* {tipo}\n\n"
                f"🌍 *CONFLUENCIA TOTAL (1M a 4H):*\n{reporte_total}\n"
                f"💰 *Precio Actual:* `{round(df.iloc[-1]['close'], 5)}`"
            )
            enviar_telegram(msg)
            print(f"✅ Señal enviada: {nombre_simbolo} Pullback Ultra-Pro")
            senales_enviadas_cruces_precisos[clave_base] = True

async def main():
    print("Scanner V7 Ultra-Precisión Online ✅")
    enviar_telegram("Scanner V7 Ultra-Precisión Online ✅\nEstrategia: Pullback tras Tendencia Larga\nTemporalidades: 5M a 4H.")
    
    uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
    
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nombre_simbolo, simbolo_api in SIMBOLOS_API.items():
                        for n_tf, v_tf in TFS_SCAN_PRECISO.items():
                            await analizar_estrategia_cruce_pulback_precisa(ws, nombre_simbolo, simbolo_api, n_tf, v_tf)
                            # Pequeña pausa para no saturar la API de Deriv
                            await asyncio.sleep(0.5) 
                    
                    # Espera antes de la siguiente ronda de escaneo global
                    await asyncio.sleep(15)
        except Exception as e:
            print(f"Conexión perdida, reconectando... Error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
