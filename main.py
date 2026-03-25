import asyncio
import pandas as pd
import requests
from deriv_api import DerivAPI

# --- CONFIGURACIÓN DE ACCESO ---
# REEMPLAZA el número 00000 por tu App ID de 5 dígitos que sacaste del Dashboard
APP_ID = '00000' 
TOKEN_READ = 'PBnrww9aT2GTDdW'
TG_TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
TG_CHAT_ID = '8236681412'

# Diccionarios de memoria para evitar duplicados en la nube
senales_enviadas = {}
cruces_confirmados = {}

# Mapeo de Símbolos Técnicos para Deriv API
SIMBOLOS_DERIV = {
    "Boom 1000 Index": "1HZ1000V", "Boom 500 Index": "1HZ500V", "Boom 300 Index": "1HZ300V",
    "Crash 1000 Index": "1HZ1000V", "Crash 500 Index": "1HZ500V", "Crash 300 Index": "1HZ300V",
    "Volatility 75 Index": "R_75", "Volatility 100 Index": "R_100", "Volatility 10 (1s) Index": "1HZ10V",
    "BTCUSD": "cryBTCUSD", "ETHUSD": "cryETHUSD", "XAUUSD": "frxXAUUSD"
}

TFS_SCAN = {"5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try: requests.post(url, data={"chat_id": TG_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"})
    except: print("❌ Error Telegram")

async def obtener_datos(api, simbolo, granularity, count=500):
    try:
        r = await api.ticks_history({'ticks_history': simbolo, 'adjust_start_time': 1, 'count': count, 'end': 'latest', 'style': 'candles', 'granularity': granularity})
        df = pd.DataFrame(r['candles'])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        return df
    except: return None

async def analizar_estrategia(df, simbolo_mt5, tf_nombre):
    global cruces_confirmados, senales_enviadas
    clave = f"{simbolo_mt5}_{tf_nombre}_pback"
    
    # --- LÓGICA DE ORO PROTEGIDA (PULLBACK ULTRA-PRECISIÓN) ---
    df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    i_cross, dir_cross = -1, None
    for i in range(len(df)-60, len(df)):
        v, p = df.iloc[i], df.iloc[i-1]
        if (v['ema30'] < v['ema50']) and not (p['ema30'] < p['ema50']): i_cross, dir_cross = i, "SELL"
        elif (v['ema30'] > v['ema50']) and not (p['ema30'] > v['ema50']): i_cross, dir_cross = i, "BUY"
    
    if i_cross == -1: return

    # Filtro 50 velas previas (80% limpieza)
    v_pre = df.iloc[i_cross-50 : i_cross]
    if len(v_pre) < 50: return
    limpieza = (v_pre['ema30'] > v_pre['ema50']).sum() if dir_cross == "SELL" else (v_pre['ema30'] < v_pre['ema50']).sum()
    if limpieza < 40: return

    # Control de duplicados por cruce
    if clave not in cruces_confirmados or cruces_confirmados[clave] != i_cross:
        cruces_confirmados[clave] = i_cross
        if clave in senales_enviadas: del senales_enviadas[clave]

    if clave in senales_enviadas: return

    # Retest Preciso (Margen 0.005%)
    i_retest = -1
    for i in range(i_cross + 5, len(df)):
        v = df.iloc[i]
        margen = v['ema30'] * 0.00005
        if dir_cross == "SELL":
            if v['high'] >= (v['ema30'] - margen) and v['close'] < v['ema50']: i_retest = i; break
        else:
            if v['low'] <= (v['ema30'] + margen) and v['close'] > v['ema50']: i_retest = i; break

    # Disparo de señal en cierre de vela
    if i_retest >= len(df) - 2:
        tipo = "🔴 VENTA" if dir_cross == "SELL" else "🔵 COMPRA"
        if ("Crash" in simbolo_mt5 and dir_cross == "BUY") or ("Boom" in simbolo_mt5 and dir_cross == "SELL"): return
        
        msg = (
            f"💎 *ALERTA: PULLBACK CLOUD (Deriv)* 💎\n\n"
            f"📊 *Mercado:* `{simbolo_mt5}`\n"
            f"⏱️ *TF:* {tf_nombre}\n"
            f"🎯 *Acción:* {tipo}\n"
            f"✅ *Estado:* Tendencia Limpia Confirmada\n"
            f"💰 *Precio:* `{round(df.iloc[-1]['close'], 5)}`"
        )
        enviar_telegram(msg)
        senales_enviadas[clave] = True

async def main():
    api = DerivAPI(app_id=APP_ID)
    await api.authorize(TOKEN_READ)
    enviar_telegram("🚀 Scanner V7 Cloud Online ✅\nServidor: Railway/Render\nEstrategia: Pullback Ultra-Precisión")

    while True:
        for simb_mt5, simb_deriv in SIMBOLOS_DERIV.items():
            for tf_n, tf_v in TFS_SCAN.items():
                df = await obtener_datos(api, simb_deriv, tf_v)
                if df is not None: await analizar_estrategia(df, simb_mt5, tf_n)
        await asyncio.sleep(20)

if __name__ == "__main__":
    asyncio.run(main())
