import asyncio
import websockets
import json
import pandas as pd
import requests
from datetime import datetime

# --- CONFIGURACIÓN CRÍTICA ---
APP_ID = '1089' 
TOKEN_TELEGRAM = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
CHAT_ID = '8236681412'

# --- ACTIVOS A ESCANEAR ---
SIMBOLOS = {
    "Volatility 75 Index": "R_75",
    "Boom 1000 Index": "1HZ1000V",
    "Crash 1000 Index": "1HZ1000V",
    "BTCUSD": "cryBTCUSD"
}

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error Telegram: {e}")

async def obtener_datos(symbol_code):
    uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
    async with websockets.connect(uri) as websocket:
        # Pedimos 150 velas para asegurar el cálculo de la EMA 100
        request = {
            "ticks_history": symbol_code,
            "adjust_start_time": 1,
            "count": 150,
            "end": "latest",
            "start": 1,
            "style": "candles",
            "granularity": 60 # 1 Minuto
        }
        await websocket.send(json.dumps(request))
        response = await websocket.recv()
        data = json.loads(response)
        
        if "candles" in data:
            df = pd.DataFrame(data["candles"])
            df['close'] = df['close'].astype(float)
            return df
        return None

def analizar_pullback(df, nombre):
    # Cálculo de Indicadores
    df['ema30'] = df['close'].ewm(span=30, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
    
    ultima = df.iloc[-1]
    previa = df.iloc[-2]
    
    # Lógica de Pullback: Cruce de EMA 30 sobre 50 + Testeo de la 30
    compra = (previa['ema30'] > previa['ema50']) and (ultima['close'] <= ultima['ema30']) and (ultima['close'] > ultima['ema50'])
    venta = (previa['ema30'] < previa['ema50']) and (ultima['close'] >= ultima['ema30']) and (ultima['close'] < ultima['ema50'])

    if compra:
        enviar_telegram(f"🔵 *POSIBLE COMPRA (Pullback)*\nActivo: {nombre}\nPrecio: {ultima['close']}\nEstrategia: EMA 30/50 Cross")
    elif venta:
        enviar_telegram(f"🔴 *POSIBLE VENTA (Pullback)*\nActivo: {nombre}\nPrecio: {ultima['close']}\nEstrategia: EMA 30/50 Cross")

async def main():
    print("Scanner V7 Cloud Online ✅")
    enviar_telegram("🚀 *Scanner V7 Super Rápido Activo*\nIniciando vigilancia de Pullbacks en 1M...")
    
    while True:
        try:
            for nombre, codigo in SIMBOLOS.items():
                df = await obtener_datos(codigo)
                if df is not None:
                    analizar_pullback(df, nombre)
            
            # Esperamos 1 minuto para el siguiente cierre de vela
            await asyncio.sleep(60)
        except Exception as e:
            print(f"Error en el bucle: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
