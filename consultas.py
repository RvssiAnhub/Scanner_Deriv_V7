import asyncio
import websockets
import json
import pandas as pd
import requests
from telegram.ext import Application, MessageHandler, filters

# --- CONFIGURACIÓN ---
TOKEN = '8717928690:AAHZm1cHhBBXrl3BokW7PXSjvFPrEYJeA-E'
APP_ID = '1089'

# LISTADO MAESTRO ORGANIZADO POR CATEGORÍAS
ACTIVOS_DETALLADOS = {
    "--- 🚀 BOOM & CRASH ---": "header",
    "B1000": "BOOM1000", "B500": "BOOM500", "B300": "BOOM300", "B600": "BOOM600", "B900": "BOOM900",
    "C1000": "CRASH1000", "C500": "CRASH500", "C300": "CRASH300", "C600": "CRASH600", "C900": "CRASH900",
    
    "--- 📈 VOLATILITY ---": "header",
    "V5": "R_5", "V10": "R_10", "V15": "R_15", "V25": "R_25", "V30": "R_30", "V50": "R_50", "V75": "R_75", "V90": "R_90", "V100": "R_100",
    
    "--- ⚡ JUMP ---": "header",
    "J10": "JD10", "J25": "JD25", "J50": "JD50", "J75": "JD75", "J100": "JD100",
    
    "--- 👣 STEP & MULTI ---": "header",
    "Step": "stpRNG", "S200": "STP200", "S500": "STP500", "M-S2": "MSTEP2", "M-S4": "MSTEP4",
    
    "--- 💎 DEX INDICES ---": "header",
    "D600-U": "DEX600U", "D600-D": "DEX600D", "D900-U": "DEX900U", "D1500-D": "DEX1500D",
    
    "--- 🌍 GLOBALES & CRYPTO ---": "header",
    "ORO": "frxXAUUSD", "PLATA": "frxXAGUSD", "BTC": "cryBTCUSD", "ETH": "cryETHUSD", "US100": "otcUSTECH", "WS30": "otcWALLST"
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
            
            # LÓGICA DE ACUMULACIÓN (Diferencia menor al 0.02%)
            diff = abs(e30 - e50)
            threshold = e50 * 0.0002 
            
            if diff < threshold: return "⚪"
            return "🟢" if e30 > e50 else "🔴"
    except: pass
    return "➖"

async def responder_tendencias(update, context):
    user_text = update.message.text.lower()
    if "tendencias" in user_text:
        msg_wait = await update.message.reply_text("⏳ *Escaneando mercados...*", parse_mode="Markdown")
        
        uri = f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}"
        reporte = "📊 *TENDENCIAS LIVE*\n`🟢Subida | 🔴Bajada | ⚪Rango` \n"
        reporte += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        
        async with websockets.connect(uri) as ws:
            for nombre, api_code in ACTIVOS_DETALLADOS.items():
                if api_code == "header":
                    reporte += f"\n*{nombre}*\n"
                    continue
                
                linea = f"`{nombre:7}`" # Alineación fija para que se vea ordenado
                for label, secs in TFS_FULL.items():
                    res = await obtener_tendencia(ws, api_code, secs)
                    linea += f" {res}"
                reporte += linea + "\n"
                await asyncio.sleep(0.05) 
        
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=msg_wait.message_id,
            text=reporte,
            parse_mode="Markdown"
        )

def main():
    print("🤖 Bot de Consultas Pro iniciado...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, responder_tendencias))
    app.run_polling()

if __name__ == "__main__":
    main()
