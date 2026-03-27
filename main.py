import asyncio
import websockets
import json
import pandas as pd
import pandas_ta as ta
import requests
import io
import time
import matplotlib
# Configuración headless obligatoria para Railway (Agg)
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime

# =============================================================
# 1. CONFIGURACIÓN QUIRÚRGICA DE IDENTIDAD
# =============================================================
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'
APP_ID = '1089'  # Demo de Deriv

# Temporalidad ÚNICA operativa
TF_M5 = 300 

# Diccionario Quirúrgico de Activos (Boom y Crash)
MERCADOS = {
    "Boom 1000 Index": "BOOM1000", "Boom 900 Index": "BOOM900", "Boom 600 Index": "BOOM600", "Boom 500 Index": "BOOM500", "Boom 300 Index": "BOOM300",
    "Crash 1000 Index": "CRASH1000", "Crash 900 Index": "CRASH900", "Crash 600 Index": "CRASH600", "Crash 500 Index": "CRASH500", "Crash 300 Index": "CRASH300"
}

alertas_enviadas = {}

# =============================================================
# 2. MOTOR DE COMUNICACIÓN (TELEGRAM + GRÁFICOS)
# =============================================================
def enviar_telegram_con_foto(mensaje, bufer_foto):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    try:
        # Reiniciar puntero del bufer a cero para lectura
        bufer_foto.seek(0)
        archivos = {'photo': ('chart.png', bufer_foto, 'image/png')}
        payload = {'chat_id': CHAT_ID, 'caption': mensaje, 'parse_mode': 'Markdown'}
        requests.post(url, data=payload, files=archivos, timeout=10)
    except: pass

async def pedir_velas(ws, sid, count=200):
    req = {"ticks_history": sid, "count": count, "end": "latest", "style": "candles", "granularity": TF_M5}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data and data["candles"]:
        df = pd.DataFrame(data["candles"])
        for c in ['close', 'high', 'low', 'open']: df[c] = df[c].astype(float)
        df['time'] = pd.to_datetime(df['epoch'], unit='s')
        df.set_index('time', inplace=True)
        return df
    return None

# =============================================================
# 3. MOTOR GRÁFICO (RECREACIÓN DE CAPTURA EN MEMORIA Agg)
# =============================================================
def generar_captura_fibo_m5(df, nombre_mercado, nivel_fibo, es_boom):
    """
    Recrea quirúrgicamente el gráfico en la RAM para enviarlo como captura.
    """
    # Usamos las últimas 80 velas M5 para contexto visual claro
    df_plot = df.iloc[-80:]
    
    # Color quirúrgico para la línea Fibo 23.6% solicitado
    fibo_color = '#cc00cc' # Púrpura Prominente

    # Crear la línea de Fibonacci programáticamente como un overlay
    # ( mplfinance no dibuja líneas horizontales estáticas fácilmente,
    #   así que creamos una lista de precios constante )
    fibo_series = [nivel_fibo] * len(df_plot)
    ap_fibo = mpf.make_addplot(fibo_series, color=fibo_color, width=1.5, linestyle='-', panel=0)

    # Configuración de Estilo de Gráfico Profesional (Dark Theme para trading)
    style = mpf.make_mpf_style(base_mpf_style='charles', marketcolors=mpf.make_marketcolors(up='green', down='red', inherit=True), gridcolor='gray', facecolor='#121212', edgecolor='#222222', figcolor='#121212')

    # Guardar imagen directamente en la RAM (io.BytesIO) para velocidad
    bufer = io.BytesIO()
    
    mpf.plot(df_plot, type='candle', style=style, addplot=ap_fibo,
             title=f'Señal Fibo 23.6% - {nombre_mercado} (M5)',
             ylabel='Price', volume=False, datetime_format='%H:%M', 
             savefig=dict(fname=bufer, format='png'))
    
    bufer.seek(0)
    return bufer

# =============================================================
# 4. MATRIZ LÓGICA V13.5: FRANCOTIRADOR FIBO-GRÁFICO
# =============================================================
async def analizar_fibo_m5(ws, nombre, sid):
    global alertas_enviadas
    df = await pedir_velas(ws, sid)
    if df is None or len(df) < 110: return

    actual = df.iloc[-1]
    
    # ID de alerta por vela M5 para no duplicar
    alerta_id = f"{sid}_{TF_M5}_{actual['epoch']}"
    if alerta_id in alertas_enviadas: return

    # 1. TRAZO DE FIBONACCI (Rigor de Imagen: 100% Top, 0% Bottom en retroceso largo)
    # Buscamos el rango de las últimas 100 velas M5 operativo
    rango_lookback = df.iloc[-100:-1]
    historial_high = rango_lookback['high'].max()
    historial_low = rango_lookback['low'].min()
    distancia = historial_high - historial_low
    
    if distancia <= 0: return # Evitar flat markets

    # Nivel 23.6% exacto solicitado
    disparo = False
    es_boom = "Boom" in nombre
    
    if es_boom:
        # Boom: Spike alcista. El high toca o cruza hacia arriba el Fibo 23.6%.
        nivel_236 = historial_low + (distancia * 0.236)
        # Margen técnico de proximidad del 0.01%
        if actual['high'] >= (nivel_236 - (nivel_236 * 0.0001)): disparo = True
    else: # Crash
        # Crash: Spike bajista. El low toca o cruza hacia abajo el Fibo 23.6%.
        nivel_236 = historial_high - (distancia * 0.236)
        # Margen técnico de proximidad del 0.01%
        if actual['low'] <= (nivel_236 + (nivel_236 * 0.0001)): disparo = True

    # 2. GATILLO INMEDIATO AL TOQUE
    if disparo:
        alertas_enviadas[alerta_id] = True
        
        # MEDICIÓN TÉCNICA (Informativa, NO interfiere en la señal)
        # Stochastic (14,3,3) y CCI (14) basado minuciosamente en imagen.
        stoch_df = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3, smooth_k=3)
        val_k = stoch_df.iloc[-1]['STOCHk_14_3_3']
        val_d = stoch_df.iloc[-1]['STOCHd_14_3_3']
        
        val_cci = ta.cci(df['high'], df['low'], df['close'], length=14).iloc[-1]
        
        estado = ""
        if es_boom:
            # Sobreventa extrema para Booms.
            estado = "🔴 SOBREVENTA DETECTADA" if (val_k < 20 or val_cci < -100) else "⚪ Zona Neutra"
        else:
            # Sobrecompra extrema para Crashes.
            estado = "🟢 SOBRECOMPRA DETECTADA" if (val_k > 80 or val_cci > 100) else "⚪ Zona Neutra"

        # 3. GENERACIÓN DE CAPTURA PROGRAMÁTICA
        chart_buf = generar_captura_fibo_m5(df, nombre, nivel_236, es_boom)
        
        # MENSAJE TÉCNICO DETALLADO SOLICITADO
        msg = (f"🎯 **ALERTA FIBO 23.6% - M5** 🎯\n\n"
               f"📊 *Mercado:* `{nombre}` | TF Señal: `M5`\n"
               f"⚡ *Acción:* **{'🟢 COMPRA' if es_boom else '🔴 VENTA'} (Spike Detectado)**\n\n"
               f"📏 **Nivel Fibonacci 23.6%:** `{round(nivel_236, 5)}`\n"
               f"📍 **Precio Spike Actual:** `{round(actual['high'] if es_boom else actual['low'], 5)}`\n"
               f"───────────────────\n"
               f"🔍 **INFO TÉCNICA (Referencia):**\n"
               f"📢 Estado Visual: `{estado}`\n"
               f"📉 Stochastic (14,3,3): `K:{round(val_k,2)} D:{round(val_d,2)}`\n"
               f"📈 CCI (14): `{round(val_cci,2)}`\n"
               f"───────────────────\n"
               f"⏰ _Scan - {datetime.now().strftime('%H:%M:%S UTC')}_")
        
        enviar_telegram_con_foto(msg, chart_buf)
        # Cerrar bufer quirúrgicamente para liberar RAM inmediatamente
        chart_buf.close()

async def loop_principal():
    uri = "wss://ws.binaryws. v3?app_id=" + APP_ID
    while True:
        try:
            async with websockets.connect(uri) as ws:
                while True:
                    for nom, sid in MERCADOS.items():
                        await analizar_fibo_m5(ws, nom, sid)
                        # Delay quirúrgico asíncrono de 0.2s para no saturar API Deriv
                        await asyncio.sleep(0.2) 
                    # Ciclo rápido en M5
                    await asyncio.sleep(15) 
        except Exception as e:
            # Reintentar conexión quirúrgicamente tras error
            await asyncio.sleep(5)

if __name__ == "__main__":
    # Mensaje de confirmación inmediata solicitado
    enviar_telegram_con_foto("📐 **Scanner Fibo 23.6% M5 Online (con Gráficos)**\nAnalizando retrocesos largos. La señal se envía al toque con captura visual técnica.", None if 'chart_buf' not in locals() else chart_buf)
    # Reemplazo por un simple mensaje de texto inicial para el main, ya que no hay chart_buf
    url_text = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url_text, json={"chat_id": CHAT_ID, "text": "📐 **Scanner Fibo 23.6% M5 Online (con Gráficos)**\n_Matriz asíncrona cargando..._", "parse_mode": "Markdown"})
    
    # Arrancar el motor asíncrono quirúrgicamente
    asyncio.run(loop_principal())
