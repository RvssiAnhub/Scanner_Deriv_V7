import asyncio
import websockets
import json
import pandas as pd
import requests

# --- CONFIGURACIÓN ---
APP_ID = '1089' 
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'

senales_enviadas_cruces_precisos = {}
cruces_confirmados_estrategia_2_precisa = {} 

SIMBOLOS_API = {
    "Boom 1000 Index": "BOOM1000", "Boom 500 Index": "BOOM500", "Boom 300 Index": "BOOM300",
    "Crash 1000 Index": "CRASH1000", "Crash 500 Index": "CRASH500", "Crash 300 Index": "CRASH300",
    "Volatility 10 Index": "R_10", "Volatility 25 Index": "R_25", "Volatility 50 Index": "R_50", "Volatility 75 Index": "R_75", "Volatility 100 Index": "R_100",
    "Volatility 10 (1s) Index": "1HZ10V", "Volatility 25 (1s) Index": "1HZ25V", "Volatility 50 (1s) Index": "1HZ50V", "Volatility 75 (1s) Index": "1HZ75V", "Volatility 100 (1s) Index": "1HZ100V",
    "Step Index": "stpRNG", "BTCUSD": "cryBTCUSD", "ETHUSD": "cryETHUSD"
}

TFS_SCAN_PRECISO = {"5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}
TFS_REPORTE_FULL = {"1M": 60, "5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}, timeout=5)
    except: print("❌ Error Telegram")

async def pedir_velas(ws, simbolo_api, tf_segundos, cantidad):
    req = {"ticks_history": simbolo_api, "adjust_start_time": 1, "count": cantidad, "end": "latest", "style": "candles", "granularity": tf_segundos}
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
    if df_t is None or len(df_t) < 60: return "S/D ⚪"
    e30 = df_t['close'].ewm(span=30, adjust=False).mean().iloc[-1]
    e50 = df_t['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    return "UP 🟢" if e30 > e50 else "DOWN 🔴"

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
    v_pre = df.iloc[i_cross - 50 : i_cross]
    limpieza = (v_pre['ema30'] > v_pre['ema50']).sum() if dir_cross == "SELL" else (v_pre['ema30'] < v_pre['ema50']).sum()
    if limpieza < 40: return
    if clave_base not in cruces_confirmados_estrategia_2_precisa or cruces_confirmados_estrategia_2_precisa[clave_base]['index'] != i_cross:
        cruces_confirmados_estrategia_2_precisa[clave_base] = {'index': i_cross, 'direction': dir_cross}
        if clave_base in senales_enviadas_cruces_precisos: del senales_enviadas_cruces_precisos[clave_base]
    if clave_base in senales_enviadas_cruces_precisos: return
    i_retest = -1
    for i in range(i_cross + 5, len(df)):
        v = df.iloc[i]
        margen = v['ema30'] * 0.00005
        if (dir_cross == "SELL" and v['high'] >= (v['ema30'] - margen)) or (dir_cross == "BUY" and v['low'] <= (v['ema30'] + margen)):
            i_retest = i; break
    if i_retest != -1 and (i_retest >= len(df) - 2):
        v_retest = df.iloc[i_retest]
        if (dir_cross == "SELL" and v_retest['close'] < v_retest['ema50']) or (dir_cross == "BUY" and v_retest['close'] > v_retest['ema50']):
            if ("Crash" in nombre_simbolo and dir_cross == "BUY") or ("Boom" in nombre_simbolo and dir_cross == "SELL"): return
            reporte_total = ""
            for n, val in TFS_REPORTE_FULL.items():
                tend = await obtener_tendencia_tf(ws, simbolo_api, val)
                reporte_total += f"• {n}: {tend}\n"
            msg = (f"💎 *ALERTA: PULLBACK ULTRA-PRECISO* 💎\n\n📊 *Mercado:* `{nombre_simbolo}`\n⏱️ *TF:* {tf_n}\n🚫 *Estado:* Tendencia Previa Confirmada ✅\n🎯 *Evento:* Toque Perfecto EMA 30\n🔥 *Acción:* {'🔴 VENTA' if dir_cross == 'SELL' else '🔵 COMPRA'}\n\n🌍 *CONFLUENCIA:*\n{reporte_total}\n💰 *Precio:* `{round(df.iloc[-1]['close'], 5)}`")
            enviar_telegram(msg)
            senales_enviadas_cruces_precisos[clave_base] = True

async def main():
    enviar_telegram("🚀 Scanner V7 Ultra-Precisión ACTIVO")
    uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nom, api in SIMBOLOS_API.items():
                        for n_tf, v_tf in TFS_SCAN_PRECISO.items():
                            await analizar_estrategia_cruce_pulback_precisa(ws, nom, api, n_tf, v_tf)
                            await asyncio.sleep(0.3)
                    await asyncio.sleep(15)
        except: await asyncio.sleep(5)

if __name__ == "__main__": asyncio.run(main())
