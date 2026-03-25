import asyncio
import websockets
import json
import pandas as pd
from telegram.ext import Application, MessageHandler, filters

# --- CONFIGURACIÓN ---
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
APP_ID = '1089'

# Nombres completos para máxima claridad
ACTIVOS_DETALLADOS = {
    "Boom 1000 Index": "BOOM1000", "Boom 500 Index": "BOOM500", "Boom 300 Index": "BOOM300",
    "Crash 1000 Index": "CRASH1000", "Crash 500 Index": "CRASH500", "Crash 300 Index": "CRASH300",
    "Volatility 10 Index": "R_10", "Volatility 25 Index": "R_25", "Volatility 50 Index": "R_50", 
    "Volatility 75 Index": "R_75", "Volatility 100 Index": "R_100",
    "Volatility 10 (1s) Index": "1HZ10V", "Volatility 25 (1s) Index": "1HZ25V", 
    "Volatility 50 (1s) Index": "1HZ50V", "Volatility 75 (1s) Index": "1HZ75V", 
    "Volatility 100 (1s) Index": "1HZ100V",
    "Step Index": "stpRNG", "BTCUSD": "cryBTCUSD", "ETHUSD": "cryETHUSD"
}

TEMPORALIDADES = {"1M": 60, "5M": 300, "15M": 900, "30M": 1800, "1H": 3600, "4H": 14400, "1D": 86400}

async def obtener_tendencia(ws, api_name, seconds):
    req = {"ticks_history": api_name, "count": 80, "end": "latest", "style": "candles", "granularity": seconds}
    await ws.send(json.dumps(req))
    resp = await ws.recv()
    data = json.loads(resp)
    if "candles" in data:
        df = pd.DataFrame(data["candles"])
        df['close'] = df['close'].astype(float)
        # Cálculo de EMAs idéntico a tu estrategia principal
        e30 = df['close'].ewm(span=30, adjust=False).mean().iloc[-1]
        e50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        return "🟢" if e30 > e50 else "🔴"
    return "⚪"

async def responder_tendencias(update, context):
    user_text = update.message.text.lower()
    # CAMBIO DE COMANDO A: Trending now
    if "trending now" in user_text:
        msg_inicial = await update.message.reply_text("⏳ *Analizando mercados (1M a 1D)...*", parse_mode="Markdown")
        
        uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
        reporte = "📋 *ESTADO DE TENDENCIAS LIVE*\n"
        reporte += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        
        async with websockets.connect(uri) as ws:
            for nombre_claro, api_code in ACTIVOS_DETALLADOS.items():
                linea = f"• *{nombre_claro}*\n└ "
                for tf_label, tf_secs in TEMPORALIDADES.items():
                    res = await obtener_tendencia(ws, api_code, tf_secs)
                    linea += f"`{tf_label}`{res}  "
                reporte += linea + "\n\n"
                await asyncio.sleep(0.1) 
        
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=msg_inicial.message_id,
            text=reporte,
            parse_mode="Markdown"
        )

def main():
    print("🤖 Bot de Consultas Live Iniciado (Comando: Trending now)")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder_tendencias))
    app.run_polling()

if __name__ == "__main__":
    main()
