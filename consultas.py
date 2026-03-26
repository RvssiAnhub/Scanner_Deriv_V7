import asyncio
import websockets
import json
import pandas as pd
from telegram.ext import Application, MessageHandler, filters

# --- CONFIGURACIÓN ---
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
APP_ID = '1089'

# CATEGORÍAS INDEPENDIENTES
CATEGORIAS = {
    "🚀 *BOOM & CRASH*": {
        "B1000": "BOOM1000", "B500": "BOOM500", "B300": "BOOM300", "B600": "BOOM600", "B900": "BOOM900",
        "C1000": "CRASH1000", "C500": "CRASH500", "C300": "CRASH300", "C600": "CRASH600", "C900": "CRASH900"
    },
    "📈 *VOLATILITY*": {
        "V5": "R_5", "V10": "R_10", "V15": "R_15", "V25": "R_25", "V30": "R_30", "V50": "R_50", "V75": "R_75", "V90": "R_90", "V100": "R_100"
    },
    "⚡ *JUMP*": {
        "J10": "JD10", "J25": "JD25", "J50": "JD50", "J75": "JD75", "J100": "JD100"
    },
    "👣 *STEP & MULTI*": {
        "Step": "stpRNG", "S200": "STP200", "S300": "STP300", "S400": "STP400", "S500": "STP500", "M-S2": "MSTEP2", "M-S3": "MSTEP3", "M-S4": "MSTEP4"
    },
    "💎 *DEX INDICES*": {
        "D600-U": "DEX600U", "D600-D": "DEX600D", "D900-U": "DEX900U", "D900-D": "DEX900D", "D1500-U": "DEX1500U", "D1500-D": "DEX1500D"
    },
    "🪙 *CRIPTOMONEDAS*": {
        "BTC": "cryBTCUSD", "ETH": "cryETHUSD"
    },
    "🔱 *METALES*": {
        "ORO": "frxXAUUSD", "PLATA": "frxXAGUSD"
    },
    "🏛️ *ÍNDICES BURSÁTILES*": {
        "US100": "otcUSTECH", "WS30": "otcWALLST"
    }
}

TFS_FULL = {"1M": 60, "15M": 900, "1H": 3600, "4H": 14400, "1D": 86400}

async def obtener_tendencia(ws, api_name, seconds):
    req = {"ticks_history": api_name, "count": 80, "end": "latest", "style": "candles", "granularity": seconds}
    try:
        await ws.send(json.dumps(req))
        resp = await ws.recv()
        data = json.loads(resp)
        if "candles" in data:
            df = pd.DataFrame(data["candles"])
            df['close'] = df['close'].astype(float)
            e30 = df['close'].ewm(span=30, adjust=False).mean().iloc[-1]
            e50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
            
            # ACUMULACIÓN (⚪)
            diff = abs(e30 - e50)
            threshold = e50 * 0.00018 
            if diff < threshold: return "⚪"
            return "🟢" if e30 > e50 else "🔴"
    except: pass
    return "➖"

async def responder_tendencias(update, context):
    user_text = update.message.text.lower()
    if "tendencias" in user_text:
        # 1. Mensaje temporal de aviso
        aviso = await update.message.reply_text("⏳ *Generando reportes separados...*", parse_mode="Markdown")
        
        uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
        
        async with websockets.connect(uri) as ws:
            for cat_nombre, activos in CATEGORIAS.items():
                # CONSTRUIMOS UN MENSAJE COMPLETAMENTE NUEVO PARA CADA CATEGORÍA
                texto_bloque = f"{cat_nombre}\n"
                texto_bloque += "`ACTIVO   1M 15M 1H 4H 1D` \n"
                texto_bloque += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
                
                for nombre, api_code in activos.items():
                    linea = f"`{nombre:7}`"
                    for label, secs in TFS_FULL.items():
                        res = await obtener_tendencia(ws, api_code, secs)
                        linea += f" {res}"
                    texto_bloque += linea + "\n"
                    await asyncio.sleep(0.02)
                
                # ENVIAR MENSAJE INDEPENDIENTE
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=texto_bloque,
                    parse_mode="Markdown"
                )
                # Pausa para asegurar que Telegram no los junte
                await asyncio.sleep(0.3)

        # 2. Borramos el aviso de "Cargando" al terminar
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=aviso.message_id)

def main():
    print("🤖 Bot de Consultas Multi-Mensaje V3 iniciado...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder_tendencias))
    app.run_polling()

if __name__ == "__main__":
    main()
