from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json
from pydantic import BaseModel
from database import init_db, BotState, TradeHistory, AppConfig

app = FastAPI(title="Indodax AutoTrade API")

# Konfigurasi CORS (Cross-Origin Resource Sharing)
# Mengizinkan Frontend Svelte (port 5173) untuk meminta data ke Backend FastAPI (port 8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Mengizinkan semua origin untuk kemudahan pengembangan
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inisialisasi Database
Session = init_db()

@app.get("/")
def read_root():
    return {"message": "AutoTrade FastAPI Server is Running 🚀"}

@app.get("/api/status")
def get_bot_status():
    """Mengembalikan status terkini dari semua koin yang dipantau (Harga, Sinyal, Saldo, MIXA AI)."""
    db = Session()
    try:
        states = db.query(BotState).all()
        result = []
        for state in states:
            result.append({
                "symbol": state.symbol,
                "current_price": state.current_price,
                "signal": state.signal,
                "mode": state.mode,
                "balances": json.loads(state.balances) if state.balances else {},
                "entry_price": state.entry_price,
                "take_profit_pct": state.take_profit_pct,
                "stop_loss_pct": state.stop_loss_pct,
                "strategy": state.strategy,
                "mixa_insight": state.mixa_insight,
                "last_update": state.last_update.isoformat() if state.last_update else None
            })
        return result
    finally:
        db.close()

@app.get("/api/history/{symbol_path:path}")
def get_trade_history(symbol_path: str):
    """Mengembalikan riwayat transaksi (BUY/SELL) untuk koin tertentu (contoh: BTC/IDR)."""
    db = Session()
    try:
        history = db.query(TradeHistory).filter_by(symbol=symbol_path).order_by(TradeHistory.timestamp.desc()).all()
        result = []
        for h in history:
            result.append({
                "id": h.id,
                "symbol": h.symbol,
                "action": h.action,
                "price": h.price,
                "nominal": h.nominal,
                "timestamp": h.timestamp.isoformat() if h.timestamp else None
            })
        return result
    finally:
        db.close()

@app.get("/api/chart/{symbol_path:path}")
def get_chart_data(symbol_path: str):
    """Mengembalikan array data Candlestick (termasuk Indikator) untuk di-render oleh Lightweight Charts."""
    db = Session()
    try:
        state = db.query(BotState).filter_by(symbol=symbol_path).first()
        if not state or not state.chart_data:
            return []
        
        return json.loads(state.chart_data)
    finally:
        db.close()

class ConfigUpdate(BaseModel):
    gemini_model: str
    initial_balance: float = 0.0

@app.get("/api/config")
def get_config():
    """Mengembalikan konfigurasi sistem, termasuk model Gemini yang aktif dan Modal Awal."""
    db = Session()
    try:
        config_model = db.query(AppConfig).filter_by(key="GEMINI_MODEL").first()
        model_name = config_model.value if config_model else "gemini-2.5-flash"
        
        config_balance = db.query(AppConfig).filter_by(key="INITIAL_BALANCE").first()
        initial_balance = float(config_balance.value) if config_balance else 0.0
        
        return {"gemini_model": model_name, "initial_balance": initial_balance}
    finally:
        db.close()

@app.post("/api/config")
def update_config(data: ConfigUpdate):
    """Memperbarui konfigurasi sistem."""
    db = Session()
    try:
        # Simpan Model
        config_model = db.query(AppConfig).filter_by(key="GEMINI_MODEL").first()
        if not config_model:
            config_model = AppConfig(key="GEMINI_MODEL", value=data.gemini_model)
            db.add(config_model)
        else:
            config_model.value = data.gemini_model
            
        # Simpan Initial Balance
        config_balance = db.query(AppConfig).filter_by(key="INITIAL_BALANCE").first()
        if not config_balance:
            config_balance = AppConfig(key="INITIAL_BALANCE", value=str(data.initial_balance))
            db.add(config_balance)
        else:
            config_balance.value = str(data.initial_balance)
            
        db.commit()
        return {"message": "Configuration updated successfully", "gemini_model": data.gemini_model, "initial_balance": data.initial_balance}
    finally:
        db.close()

class BotConfigUpdate(BaseModel):
    take_profit_pct: float
    stop_loss_pct: float
    strategy: str

@app.post("/api/bot-config/{symbol_path:path}")
def update_bot_config(symbol_path: str, config: BotConfigUpdate):
    """Memperbarui pengaturan risiko (TP/SL) dan Strategi untuk koin tertentu."""
    db = Session()
    try:
        state = db.query(BotState).filter_by(symbol=symbol_path).first()
        if not state:
            return {"error": "Coin not found"}
            
        state.take_profit_pct = config.take_profit_pct
        state.stop_loss_pct = config.stop_loss_pct
        state.strategy = config.strategy
        
        db.commit()
        return {"message": f"Configuration for {symbol_path} updated successfully"}
    finally:
        db.close()
