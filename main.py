import asyncio
import websockets
import json
import pandas as pd
import requests
from datetime import datetime

# =============================================================
# 1. CONFIGURACIÓN DE IDENTIDAD
# =============================================================
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'
APP_ID = '1089'  

MERCADOS_GAP = {
    "Vol 10": "R_10", "Vol 25": "R_25", "Vol 50": "R_50", "Vol 75": "R_75", "Vol 100": "R_100",
    "Vol 10(1s)": "1HZ10V", "Vol 25(1s)": "1HZ25V", "Vol 50(1s)": "1HZ50V", "Vol 75(1s)": "1HZ75V", "Vol 100(1s)": "1HZ100V",
    "Jump 10": "JD10", "Jump 25": "JD25", "Jump 50": "JD50", "Jump 75": "JD75", "Jump 100": "JD100",
    "Step": "stpRNG", "XAUUSD": "frxXAUUSD", "BTCUSD": "cryBTCUSD", "US Tech 100": "OTC_US100"
}

TFS = {"1M": 60, "5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400}
alertas_enviadas = {}

# =============================================================
# 2. MOTOR DE DATOS Y TENDENCIA
# =============================================================
def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}, timeout=5)
    except: pass

async def pedir_velas(ws, sid, tf_sec, count=10):
    req = {"ticks_history": sid, "count": count, "end": "latest", "style": "candles", "granularity": tf_sec}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data and data["candles"]:
        df = pd.DataFrame(data["candles"])
        for c in ['close', 'high', 'low', 'open']: df[c] = df[c].astype(float)
        return df
    return None

async def obtener_tendencia_pa(ws, sid, tf_sec):
    df = await pedir_velas(ws, sid, tf_sec, count=4)
    if df is None or len(df) < 3: return "⚪"
    c1, c2 = df.iloc[-3], df.iloc[-2]
    # Lógica de máximos y mínimos (Price Action)
    if c2['high'] > c1['high'] and c2['low'] > c1['low']: return "🟢"
    elif c2['high'] < c1['high'] and c2['low'] < c1['low']: return "🔴"
    else: return "🟢" if c2['close'] > c2['open'] else "🔴"

# =============================================================
# 3. NÚCLEO ALGORÍTMICO: GAP + CONFLUENCIA MACRO OBLIGATORIA
# =============================================================
async def analizar_gap_mtf(ws, nombre, sid):
    global alertas_enviadas
    df_m1 = await pedir_velas(ws, sid, TFS["1M"], count=5)
    if df_m1 is None or len(df_m1) < 4: return

    c_base, c_gap, c_conf, c_actual = df_m1.iloc[-4], df_m1.iloc[-3], df_m1.iloc[-2], df_m1.iloc[-1]
    alerta_id = f"{sid}_GAP_{c_conf['epoch']}"
    if alerta_id in alertas_enviadas: return

    # Lógica de colores para M1
    es_compra = (c_base['close'] > c_base['open']) and (c_gap['close'] > c_gap['open']) and (c_conf['close'] > c_conf['open'])
    es_venta = (c_base['close'] < c_base['open']) and (c_gap['close'] < c_gap['open']) and (c_conf['close'] < c_conf['open'])

    señal = None
    color_m1 = ""

    # Detección de GAP según estrategia (1M)
    if es_compra:
        if (c_gap['open'] - c_base['close']) >= (c_base['close'] * 0.00005):
            if c_conf['low'] >= c_gap['low']: # Regla de Oro 2da vela
                señal = "COMPRA"
                color_m1 = "🟢"

    elif es_venta:
        if (c_base['close'] - c_gap['open']) >= (c_base['close'] * 0.00005):
            if c_conf['high'] <= c_gap['high']: # Regla de Oro 2da vela
                señal = "VENTA"
                color_m1 = "🔴"

    if señal:
        # Escaneo de tendencias macro
        t_5m = await obtener_tendencia_pa(ws, sid, TFS["5M"])
        t_15m = await obtener_tendencia_pa(ws, sid, TFS["15M"])
        t_30m = await obtener_tendencia_pa(ws, sid, TFS["30M"])
        t_1h = await obtener_tendencia_pa(ws, sid, TFS["1H"])
        t_4h = await obtener_tendencia_pa(ws, sid, TFS["4H"])

        # FILTRO DE ALINEACIÓN OBLIGATORIA (30M, 1H, 4H)
        alineado = False
        if señal == "COMPRA" and t_30m == "🟢" and t_1h == "🟢" and t_4h == "🟢":
            alineado = True
        elif señal == "VENTA" and t_30m == "🔴" and t_1h == "🔴" and t_4h == "🔴":
            alineado = True

        if alineado:
            alertas_enviadas[alerta_id] = True
            msg = (f"🚀 **PATRÓN GAP + MACRO ALINEADO** 🚀\n\n"
                   f"📊 *Mercado:* `{nombre}` | TF: `1M`\n"
                   f"🎯 *Acción:* **{color_m1} {señal}**\n"
                   f"📍 *Precio:* `{round(c_actual['open'], 5)}`\n\n"
                   f"🌎 **ESTADO MULTI-TF:**\n"
                   f"• `1M:`  {color_m1} (Gatillo)\n"
                   f"• `5M:`  {t_5m} (Ignorado)\n"
                   f"• `15M:` {t_15m} (Ignorado)\n"
                   f"• `30M:` {t_30m} ✅\n"
                   f"• `1H:`  {t_1h} ✅\n"
                   f"• `4H:`  {t_4h} ✅\n"
                   f"───────────────────\n"
                   f"💎 _Tendencia Institucional Confirmada_")
            enviar_telegram(msg)

async def loop_principal():
    uri = "wss://ws.binaryws.com/websockets/v3?app_id=" + APP_ID
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nom, sid in MERCADOS_GAP.items():
                        await analizar_gap_mtf(ws, nom, sid)
                        await asyncio.sleep(0.05)
                    await asyncio.sleep(2)
        except: await asyncio.sleep(2)

if __name__ == "__main__":
    enviar_telegram("🛡️ **Sniper GAP V2.2 Online**\n_Filtro Estricto: 30M, 1H y 4H obligatorios._")
    asyncio.run(loop_principal())1
