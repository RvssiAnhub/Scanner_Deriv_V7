import asyncio
import websockets
import json
import pandas as pd
from telegram.ext import Application, MessageHandler, filters

# --- CONFIGURACIÓN ---
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
APP_ID = '1089'

# Diccionario con nombres específicos para que no adivines
ACTIVOS_DETALLADOS = {
    "Boom 1000": "BOOM1000", "Boom 500": "BOOM500", "Boom 300": "BOOM300",
    "Crash 1000": "CRASH1000", "Crash 500": "CRASH500", "Crash 300": "CRASH300",
    "Volatility 10": "R_10", "Volatility 25": "R_25", "Volatility 50": "R_50", 
    "Volatility 75": "R_75", "Volatility 100": "R_100",
    "Volatility 10 (1s)": "1HZ10V", "Volatility 25 (1s)": "1HZ25V", 
    "Volatility 50 (1s)": "1HZ50V", "Volatility 75 (1s)": "1HZ75V", 
    "Volatility 100 (1s)": "1HZ100V",
    "Step Index": "stpRNG", "Bitcoin (BTC)": "cryBTCUSD", "Ethereum (ETH)": "cryETHUSD"
}

# Temporalidades para el reporte completo
TFS_FULL = {"1M": 60, "5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400, "1D": 86400}

async def obtener_tendencia(ws, api_name, seconds):
    req = {"ticks_history": api_name, "count": 80, "end": "latest", "style": "candles", "granularity": seconds}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data:
        df = pd.DataFrame(data["candles"])
        df['close'] = df['close'].astype(float)
        # Lógica de tus EMAs 30 y 50
        e30 = df['close'].ewm(span=30, adjust=False).mean().iloc[-1]
        e50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        return "🟢" if e30 > e50 else "🔴"
    return "⚪"

async def responder_tendencias(update, context):
    user_text = update.message.text.lower()
    # Responde a la palabra "tendencias"
    if "tendencias" in user_text:
        msg_wait = await update.message.reply_text("⏳ *Analizando todos los mercados...* \nEsto tardará unos segundos.", parse_mode="Markdown")
        
        uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
        reporte = "📊 *ESTADO DE MERCADOS LIVE*\n"
        reporte += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        
        async with websockets.connect(uri) as ws:
            for nombre, api_code in ACTIVOS_DETALLADOS.items():
                linea = f"• *{nombre}*\n└ "
                for label, secs in TFS_FULL.items():
                    res = await obtener_tendencia(ws, api_code, secs)
                    linea += f"`{label}`{res}  "
                reporte += linea + "\n\n"
                await asyncio.sleep(0.05) # Pausa mínima para no saturar la API
        
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=msg_wait.message_id,
            text=reporte,
            parse_mode="Markdown"
        )

def main():
    print("🤖 Bot de Consultas de Tendencias Iniciado...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder_tendencias))
    app.run_polling()

if __name__ == "__main__":
    main()
