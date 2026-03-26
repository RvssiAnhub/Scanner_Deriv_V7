import asyncio
import websockets
import json
import pandas as pd
import requests
from telegram.ext import Application

# --- CONFIGURACIÓN DE IDENTIDAD ---
APP_ID = '1089' 
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'

# Memorias de señales (No se tocan)
senales_enviadas_cruces_precisos = {}
cruces_confirmados_estrategia_2_precisa = {} 

# --- MERCADOS DERIV API ---
SIMBOLOS_API = {
    "B1000": "BOOM1000", "B500": "BOOM500", "B300": "BOOM300", "B600": "BOOM600", "B900": "BOOM900",
    "C1000": "CRASH1000", "C500": "CRASH500", "C300": "CRASH300", "C600": "CRASH600", "C900": "CRASH900",
    "V5": "R_5", "V10": "R_10", "V15": "R_15", "V25": "R_25", "V30": "R_30", "V50": "R_50", "V75": "R_75", "V90": "R_90", "V100": "R_100",
    "J10": "JD10", "J25": "JD25", "J50": "JD50", "J75": "JD75", "J100": "JD100",
    "Step": "stpRNG", "S200": "STP200", "S500": "STP500", "M-S2": "MSTEP2", "M-S4": "MSTEP4",
    "D600-U": "DEX600U", "D600-D": "DEX600D", "D900-U": "DEX900U", "D1500-D": "DEX1500D",
    "ORO": "frxXAUUSD", "PLATA": "frxXAGUSD", "BTC": "cryBTCUSD", "ETH": "cryETHUSD",
    "US100": "otcUSTECH", "WS30": "otcWALLST"
}

# ESCANEO: Ahora incluimos 5M
TFS_SCAN = {"5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}
TFS_FULL = {"1M": 60, "5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400, "1D": 86400}

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

# --- ESTRATEGIA CON ALINEACIÓN OBLIGATORIA ---
async def analizar_estrategia_cruce_pulback_precisa(ws, nombre_simbolo, simbolo_api, tf_n, tf_v):
    global cruces_confirmados_estrategia_2_precisa, senales_enviadas_cruces_precisos
    clave_base = f"{nombre_simbolo}_{tf_n}_pback_pro"
    
    df = await pedir_velas(ws, simbolo_api, tf_v, 500)
    if df is None or len(df) < 300: return
    
    df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    i_cross, dir_cross = -1, None
    for i in range(len(df)-60, len(df)):
        v, p = df.iloc[i], df.iloc[i-1]
        if (v['ema30'] < v['ema50']) and not (p['ema30'] < p['ema50']): i_cross, dir_cross = i, "SELL"
        elif (v['ema30'] > v['ema50']) and not (p['ema30'] > v['ema50']): i_cross, dir_cross = i, "BUY"
    
    if i_cross == -1: return

    # FILTRO DE LIMPIEZA PREVIA
    v_pre = df.iloc[i_cross - 50 : i_cross]
    limpieza = (v_pre['ema30'] > v_pre['ema50']).sum() if dir_cross == "SELL" else (v_pre['ema30'] < v_pre['ema50']).sum()
    if limpieza < 40: return 

    if clave_base not in cruces_confirmados_estrategia_2_precisa or cruces_confirmados_estrategia_2_precisa[clave_base]['index'] != i_cross:
        cruces_confirmados_estrategia_2_precisa[clave_base] = {'index': i_cross, 'direction': dir_cross}
        if clave_base in senales_enviadas_cruces_precisos: del senales_enviadas_cruces_precisos[clave_base]
    
    if clave_base in senales_enviadas_cruces_precisos: return

    # DETECCIÓN DE PULLBACK (TOQUE EMA 30)
    i_retest = -1
    for i in range(i_cross + 5, len(df)):
        v = df.iloc[i]
        margen = v['ema30'] * 0.00005 
        if (dir_cross == "SELL" and v['high'] >= (v['ema30'] - margen)) or (dir_cross == "BUY" and v['low'] <= (v['ema30'] + margen)):
            i_retest = i; break
            
    if i_retest != -1 and (i_retest >= len(df) - 2):
        v_retest = df.iloc[i_retest]
        if (dir_cross == "SELL" and v_retest['close'] < v_retest['ema50']) or (dir_cross == "BUY" and v_retest['close'] > v_retest['ema50']):
            
            # --- 🛡️ FILTRO DE ALINEACIÓN 1H Y 4H (NUEVO) ---
            t_1h = await obtener_tendencia_tf(ws, simbolo_api, 3600)
            t_4h = await obtener_tendencia_tf(ws, simbolo_api, 14400)
            
            alineado = False
            if dir_cross == "BUY" and t_1h == "🟢" and t_4h == "🟢": alineado = True
            elif dir_cross == "SELL" and t_1h == "🔴" and t_4h == "🔴": alineado = True
            
            if not alineado: return # Si no hay alineación con los grandes, abortamos señal
            # ----------------------------------------------

            if ("Crash" in nombre_simbolo and dir_cross == "BUY") or ("Boom" in nombre_simbolo and dir_cross == "SELL"): return
            
            reporte_total = ""
            for n, val in TFS_FULL.items():
                tend = await obtener_tendencia_tf(ws, simbolo_api, val)
                reporte_total += f"• {n}: {tend}\n"
                
            msg = (f"🛡️ *SEÑAL ALINEADA (H1+H4)* 🛡️\n\n📊 *Mercado:* `{nombre_simbolo}`\n⏱️ *TF:* {tf_n}\n🎯 *Evento:* Pullback Confirmado\n🔥 *Acción:* {'🔴 VENTA' if dir_cross == 'SELL' else '🔵 COMPRA'}\n\n🌍 *ALINEACIÓN TOTAL:*\n{reporte_total}\n💰 *Precio:* `{round(df.iloc[-1]['close'], 5)}`")
            enviar_telegram_sync(msg)
            senales_enviadas_cruces_precisos[clave_base] = True

async def loop_escaneo():
    uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nom, api in SIMBOLOS_API.items():
                        for n_tf, v_tf in TFS_SCAN.items():
                            await analizar_estrategia_cruce_pulback_precisa(ws, nom, api, n_tf, v_tf)
                            await asyncio.sleep(0.3)
                    await asyncio.sleep(15)
        except: await asyncio.sleep(5)

async def main():
    enviar_telegram_sync("🚀 Scanner V8.0 Online\n🛡️ Filtro activo: Señales alineadas con 1H y 4H")
    await loop_escaneo()

if __name__ == "__main__":
    asyncio.run(main())
