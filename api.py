from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import json
import os
import uuid
from typing import Optional
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

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    db = Session()
    try:
        db_token = db.query(AppConfig).filter_by(key="AUTH_TOKEN").first()
        if not db_token or db_token.value != token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sesi tidak valid atau telah berakhir. Silakan login kembali.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    finally:
        db.close()
    return token

class LoginRequest(BaseModel):
    password: str

@app.post("/api/login")
def login(req: LoginRequest):
    admin_password = os.getenv("ADMIN_PASSWORD", "mixa2026")
    if req.password != admin_password:
        raise HTTPException(status_code=401, detail="Password salah")
    
    new_token = uuid.uuid4().hex
    db = Session()
    try:
        token_conf = db.query(AppConfig).filter_by(key="AUTH_TOKEN").first()
        if not token_conf:
            token_conf = AppConfig(key="AUTH_TOKEN", value=new_token)
            db.add(token_conf)
        else:
            token_conf.value = new_token
        db.commit()
    finally:
        db.close()
        
    return {"token": new_token}

class CoinAddRequest(BaseModel):
    symbol: str

@app.post("/api/coin")
def add_coin(req: CoinAddRequest, token: str = Depends(verify_token)):
    """Menambahkan koin baru ke dalam pantauan bot."""
    db = Session()
    try:
        symbol = req.symbol.upper().strip()
        if not symbol.endswith('/IDR'):
            symbol += '/IDR'
            
        existing = db.query(BotState).filter_by(symbol=symbol).first()
        if existing:
            if not existing.is_active:
                existing.is_active = 1
                db.commit()
                return {"message": f"Koin {symbol} diaktifkan kembali"}
            raise HTTPException(status_code=400, detail=f"Koin {symbol} sudah ada dan aktif")
            
        new_state = BotState(symbol=symbol, is_active=1, signal="HOLD", mode="AUTO")
        db.add(new_state)
        db.commit()
        return {"message": f"Koin {symbol} berhasil ditambahkan"}
    finally:
        db.close()

@app.delete("/api/coin/{symbol_path:path}")
def remove_coin(symbol_path: str, token: str = Depends(verify_token)):
    """Menonaktifkan koin dari pantauan bot."""
    db = Session()
    try:
        symbol = symbol_path.replace('%2F', '/')
        existing = db.query(BotState).filter_by(symbol=symbol).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Koin tidak ditemukan")
            
        db.delete(existing)
        db.commit()
        return {"message": f"Koin {symbol} dihapus permanen"}
    finally:
        db.close()

@app.get("/api/status")
def get_bot_status(token: str = Depends(verify_token)):
    """Mengembalikan status terkini dari semua koin yang dipantau (Harga, Sinyal, Saldo, MIXA AI)."""
    db = Session()
    try:
        from database import get_wib_time
        import os
        cooldown_hours = float(os.getenv('COOLDOWN_HOURS', 2.0))
        states = db.query(BotState).all()
        result = []
        for state in states:
            cooldown_remaining_minutes = 0
            last_sell = db.query(TradeHistory).filter(TradeHistory.symbol == state.symbol, TradeHistory.action == "SELL").order_by(TradeHistory.timestamp.desc()).first()
            if last_sell and last_sell.timestamp:
                elapsed = (get_wib_time() - last_sell.timestamp).total_seconds()
                if elapsed < cooldown_hours * 3600:
                    cooldown_remaining_minutes = int((cooldown_hours * 3600 - elapsed) / 60)
            
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
                "buy_amount": state.buy_amount,
                "is_active": bool(state.is_active),
                "use_trailing_stop": bool(state.use_trailing_stop),
                "trailing_stop_pct": state.trailing_stop_pct,
                "use_dynamic_roi": bool(state.use_dynamic_roi),
                "dynamic_roi_config": state.dynamic_roi_config,
                "last_buy_time": state.last_buy_time,
                "use_dca": bool(state.use_dca),
                "dca_max_orders": state.dca_max_orders,
                "dca_step_pct": state.dca_step_pct,
                "dca_volume_scale": state.dca_volume_scale,
                "dca_completed_orders": state.dca_completed_orders,
                "total_idr_invested": state.total_idr_invested,
                "highest_price_since_buy": state.highest_price_since_buy,
                "mixa_insight": state.mixa_insight,
                "use_macro_trend": bool(state.use_macro_trend),
                "use_trailing_buy": bool(state.use_trailing_buy),
                "trailing_buy_pct": state.trailing_buy_pct,
                "use_whale_radar": bool(state.use_whale_radar),
                "use_autotune": bool(state.use_autotune),
                "last_update": state.last_update.isoformat() if state.last_update else None
            })
        return result
    finally:
        db.close()

@app.get("/api/history/{symbol_path:path}")
def get_trade_history(symbol_path: str, token: str = Depends(verify_token)):
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
                "pnl_pct": h.pnl_pct,
                "timestamp": h.timestamp.isoformat() if h.timestamp else None
            })
        return result
    finally:
        db.close()

@app.get("/api/chart/{symbol_path:path}")
def get_chart_data(symbol_path: str, token: str = Depends(verify_token)):
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
    gemini_model: Optional[str] = None
    initial_balance: Optional[float] = None
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    indodax_api_key: Optional[str] = None
    indodax_secret_key: Optional[str] = None

@app.get("/api/config")
def get_config(token: str = Depends(verify_token)):
    """Mengembalikan konfigurasi sistem, termasuk model Gemini yang aktif dan Modal Awal."""
    db = Session()
    try:
        configs = db.query(AppConfig).all()
        result = {
            "gemini_model": "gemini-2.5-flash",
            "initial_balance": 0.0,
            "telegram_token": "",
            "telegram_chat_id": "",
            "indodax_api_key": "",
            "indodax_secret_key": ""
        }
        for c in configs:
            if c.key == "GEMINI_MODEL": result["gemini_model"] = c.value
            elif c.key == "INITIAL_BALANCE": result["initial_balance"] = float(c.value) if c.value else 0.0
            elif c.key == "TELEGRAM_BOT_TOKEN": result["telegram_token"] = c.value
            elif c.key == "TELEGRAM_CHAT_ID": result["telegram_chat_id"] = c.value
            elif c.key == "INDODAX_API_KEY": result["indodax_api_key"] = c.value
            elif c.key == "INDODAX_SECRET_KEY": result["indodax_secret_key"] = c.value
        return result
    finally:
        db.close()

@app.post("/api/config")
def update_config(data: ConfigUpdate, token: str = Depends(verify_token)):
    """Memperbarui konfigurasi sistem."""
    db = Session()
    try:
        def update_or_create(key, value):
            if value is not None:
                item = db.query(AppConfig).filter_by(key=key).first()
                if not item:
                    item = AppConfig(key=key, value=str(value))
                    db.add(item)
                else:
                    item.value = str(value)

        update_or_create("GEMINI_MODEL", data.gemini_model)
        update_or_create("INITIAL_BALANCE", data.initial_balance)
        update_or_create("TELEGRAM_BOT_TOKEN", data.telegram_token)
        update_or_create("TELEGRAM_CHAT_ID", data.telegram_chat_id)
        update_or_create("INDODAX_API_KEY", data.indodax_api_key)
        update_or_create("INDODAX_SECRET_KEY", data.indodax_secret_key)
        
        db.commit()
        return {"message": "Konfigurasi berhasil disimpan"}
    finally:
        db.close()

@app.get("/api/performance")
def get_performance(token: str = Depends(verify_token)):
    """Mengembalikan data performa portofolio (PnL) untuk chart."""
    db = Session()
    try:
        # Ambil semua history SELL yang memiliki pnl_pct
        trades = db.query(TradeHistory).filter(TradeHistory.action == "SELL", TradeHistory.pnl_pct.isnot(None)).order_by(TradeHistory.timestamp.asc()).all()
        
        # Kelompokkan berdasarkan tanggal (YYYY-MM-DD)
        daily_pnl = {}
        for t in trades:
            date_str = t.timestamp.strftime("%Y-%m-%d")
            if date_str not in daily_pnl:
                daily_pnl[date_str] = {'date': date_str, 'total_pnl_pct': 0.0, 'trade_count': 0, 'win_count': 0}
            
            daily_pnl[date_str]['total_pnl_pct'] += t.pnl_pct
            daily_pnl[date_str]['trade_count'] += 1
            if t.pnl_pct > 0:
                daily_pnl[date_str]['win_count'] += 1
                
        # Konversi ke list yang terurut
        daily_list = list(daily_pnl.values())
        
        # Hitung ringkasan total
        total_trades = sum(d['trade_count'] for d in daily_list)
        total_wins = sum(d['win_count'] for d in daily_list)
        overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        overall_pnl = sum(d['total_pnl_pct'] for d in daily_list)
        
        return {
            "daily_stats": daily_list,
            "summary": {
                "total_trades": total_trades,
                "win_rate": overall_win_rate,
                "overall_pnl_pct": overall_pnl
            }
        }
    finally:
        db.close()

class TelegramTest(BaseModel):
    telegram_token: str
    telegram_chat_id: str

@app.post("/api/config/telegram_test")
def test_telegram(data: TelegramTest, token: str = Depends(verify_token)):
    """Mengirim pesan uji coba ke Telegram."""
    if not data.telegram_token or not data.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Token dan Chat ID harus diisi")
        
    try:
        from notifier import TelegramNotifier
        test_notifier = TelegramNotifier(token=data.telegram_token, chat_id=data.telegram_chat_id)
        test_notifier.send_message("🟢 **Test Ping dari MIXA AI**\nKoneksi Telegram Anda berhasil terhubung dengan Dasbor!")
        return {"message": "Test message sent successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class BacktestRequest(BaseModel):
    symbol: str = "BTC/IDR"
    timeframe: str = "15"
    strategy: str = "MA Crossover"
    initial_capital: float = 1000000.0
    use_dca: bool = False
    dca_max_orders: int = 3
    dca_step_pct: float = 3.0
    use_trailing_stop: bool = False
    trailing_stop_pct: float = 2.0

@app.post("/api/backtest")
def run_backtest(req: BacktestRequest, token: str = Depends(verify_token)):
    """Menjalankan simulasi Backtest pada 1000 candle terakhir (OHLCV)."""
    try:
        from exchange_handler import IndodaxHandler
        handler = IndodaxHandler(api_key="", secret_key="", dry_run=True)
        symbol_api = req.symbol.replace("/", "")
        
        # 1. Fetch data
        df = handler.fetch_hidden_ohlcv(symbol=symbol_api, tf=req.timeframe, limit=1000)
        if df.empty or len(df) < 60:
            raise HTTPException(status_code=400, detail="Gagal menarik data atau data terlalu sedikit")
            
        # 2. Select Strategy
        from strategy import MovingAverageStrategy, RSIBreakoutStrategy, BollingerBandsStrategy, GridTradingStrategy
        if req.strategy == "RSI Breakout":
            strat = RSIBreakoutStrategy()
        elif req.strategy == "Bollinger Bands":
            strat = BollingerBandsStrategy()
        elif req.strategy == "Grid Trading":
            strat = GridTradingStrategy()
        else:
            strat = MovingAverageStrategy()
            
        # 3. Simulation Loop
        capital = req.initial_capital
        balance = capital
        coin_held = 0.0
        entry_price = 0.0
        highest_price = 0.0
        dca_count = 0
        total_invested = 0.0
        trades = []
        
        for i in range(50, len(df)):
            current_df = df.iloc[:i+1]
            current_row = df.iloc[i]
            current_price = float(current_row['close'])
            timestamp = current_row['timestamp']
            
            signal = strat.analyze(current_df)
            
            # Trailing Stop
            if coin_held > 0 and req.use_trailing_stop:
                if current_price > highest_price:
                    highest_price = current_price
                drop_pct = ((highest_price - current_price) / highest_price) * 100
                if drop_pct >= req.trailing_stop_pct:
                    signal = "SELL"
                    
            # DCA
            if coin_held > 0 and signal != "SELL" and req.use_dca and dca_count < req.dca_max_orders:
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                drop_threshold = req.dca_step_pct * (dca_count + 1)
                if pnl_pct <= -drop_threshold:
                    dca_amount = float(balance * 0.5) # use 50% of remaining balance for DCA
                    if dca_amount > 10000:
                        balance -= dca_amount
                        total_invested += dca_amount
                        coin_held += float(dca_amount / current_price)
                        entry_price = float(total_invested / coin_held)
                        highest_price = entry_price
                        dca_count += 1
                        trades.append({"time": str(timestamp), "type": f"DCA #{dca_count}", "price": current_price, "amount": dca_amount, "pnl": None})
                        
            # Main Signals
            if signal == "BUY" and coin_held == 0:
                buy_amount = float(balance) # All-in per trade for simple backtest
                if buy_amount > 10000:
                    balance -= buy_amount
                    total_invested = buy_amount
                    coin_held = float(buy_amount / current_price)
                    entry_price = current_price
                    highest_price = current_price
                    dca_count = 0
                    trades.append({"time": str(timestamp), "type": "BUY", "price": current_price, "amount": buy_amount, "pnl": None})
                    
            elif signal == "SELL" and coin_held > 0:
                sell_amount = float(coin_held * current_price)
                pnl_pct = float(((current_price - entry_price) / entry_price) * 100)
                balance += sell_amount
                coin_held = 0.0
                trades.append({"time": str(timestamp), "type": "SELL", "price": current_price, "amount": sell_amount, "pnl": pnl_pct})
                
        # Force sell at end
        if coin_held > 0:
            current_price = float(df.iloc[-1]['close'])
            sell_amount = float(coin_held * current_price)
            pnl_pct = float(((current_price - entry_price) / entry_price) * 100)
            balance += sell_amount
            trades.append({"time": str(df.iloc[-1]['timestamp']), "type": "SELL (END)", "price": current_price, "amount": sell_amount, "pnl": pnl_pct})
            
        net_profit = float(balance - capital)
        net_profit_pct = float((net_profit / capital) * 100)
        win_trades = len([t for t in trades if t.get('pnl') is not None and t['pnl'] > 0])
        total_closed_trades = len([t for t in trades if t.get('pnl') is not None])
        win_rate = float((win_trades / total_closed_trades * 100) if total_closed_trades > 0 else 0.0)
        
        return {
            "initial_capital": float(capital),
            "final_balance": float(balance),
            "net_profit_pct": net_profit_pct,
            "win_rate": win_rate,
            "total_trades": total_closed_trades,
            "trades": trades
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Backtest error: {str(e)}")

class BotConfigUpdate(BaseModel):
    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    strategy: Optional[str] = None
    buy_amount: Optional[float] = None
    is_active: Optional[bool] = None
    entry_price: Optional[float] = None
    use_trailing_stop: Optional[bool] = None
    trailing_stop_pct: Optional[float] = None
    highest_price_since_buy: Optional[float] = None
    use_dynamic_roi: Optional[bool] = None
    dynamic_roi_config: Optional[str] = None
    last_buy_time: Optional[float] = None
    use_dca: Optional[bool] = None
    dca_max_orders: Optional[int] = None
    dca_step_pct: Optional[float] = None
    dca_volume_scale: Optional[float] = None
    dca_completed_orders: Optional[int] = None
    total_idr_invested: Optional[float] = None
    use_macro_trend: Optional[bool] = None
    use_trailing_buy: Optional[bool] = None
    trailing_buy_pct: Optional[float] = None
    trailing_buy_active: Optional[bool] = None
    trailing_buy_lowest_price: Optional[float] = None
    use_whale_radar: Optional[bool] = None
    use_autotune: Optional[bool] = None

@app.post("/api/bot-config/{symbol_path:path}")
def update_bot_config(symbol_path: str, config: BotConfigUpdate, token: str = Depends(verify_token)):
    """Memperbarui pengaturan risiko (TP/SL) dan Strategi untuk koin tertentu."""
    db = Session()
    try:
        state = db.query(BotState).filter_by(symbol=symbol_path).first()
        if not state:
            return {"error": "Coin not found"}
            
        if config.take_profit_pct is not None:
            state.take_profit_pct = config.take_profit_pct
        if config.stop_loss_pct is not None:
            state.stop_loss_pct = config.stop_loss_pct
        if config.strategy is not None:
            state.strategy = config.strategy
        if config.buy_amount is not None:
            state.buy_amount = config.buy_amount
        if config.is_active is not None:
            state.is_active = 1 if config.is_active else 0
        if config.entry_price is not None:
            state.entry_price = config.entry_price
            # Reset IDR Invested agar main.py bisa menghitung ulang (jika manual entry price)
            state.total_idr_invested = 0.0
            
            # Auto-set last_buy_time if entry_price is set manually and last_buy_time is 0
            if config.entry_price > 0 and (state.last_buy_time or 0.0) == 0.0:
                import time
                state.last_buy_time = time.time()
            elif config.entry_price == 0:
                state.last_buy_time = 0.0
                state.highest_price_since_buy = 0.0
                state.dca_completed_orders = 0
        if config.use_trailing_stop is not None:
            state.use_trailing_stop = 1 if config.use_trailing_stop else 0
        if config.trailing_stop_pct is not None:
            state.trailing_stop_pct = config.trailing_stop_pct
        if config.highest_price_since_buy is not None:
            state.highest_price_since_buy = config.highest_price_since_buy
        if config.use_dynamic_roi is not None:
            state.use_dynamic_roi = 1 if config.use_dynamic_roi else 0
        if config.dynamic_roi_config is not None:
            state.dynamic_roi_config = config.dynamic_roi_config
        if config.last_buy_time is not None:
            state.last_buy_time = config.last_buy_time
        if config.use_dca is not None:
            state.use_dca = 1 if config.use_dca else 0
        if config.dca_max_orders is not None:
            state.dca_max_orders = config.dca_max_orders
        if config.dca_step_pct is not None:
            state.dca_step_pct = config.dca_step_pct
        if config.dca_volume_scale is not None:
            state.dca_volume_scale = config.dca_volume_scale
        if config.dca_completed_orders is not None:
            state.dca_completed_orders = config.dca_completed_orders
        if config.total_idr_invested is not None:
            state.total_idr_invested = config.total_idr_invested
        if config.use_macro_trend is not None:
            state.use_macro_trend = 1 if config.use_macro_trend else 0
        if config.use_trailing_buy is not None:
            state.use_trailing_buy = 1 if config.use_trailing_buy else 0
            if not config.use_trailing_buy:
                # Reset tracking if turned off
                state.trailing_buy_active = 0
        if config.trailing_buy_pct is not None:
            state.trailing_buy_pct = config.trailing_buy_pct
        if config.trailing_buy_active is not None:
            state.trailing_buy_active = 1 if config.trailing_buy_active else 0
        if config.trailing_buy_lowest_price is not None:
            state.trailing_buy_lowest_price = config.trailing_buy_lowest_price
        if config.use_whale_radar is not None:
            state.use_whale_radar = 1 if config.use_whale_radar else 0
        if config.use_autotune is not None:
            state.use_autotune = 1 if config.use_autotune else 0
            
        db.commit()
        return {"message": f"Configuration for {symbol_path} updated successfully"}
    finally:
        db.close()

@app.get("/api/logs")
def get_system_logs(token: str = Depends(verify_token)):
    """Mengembalikan 200 baris terakhir dari log sistem (bot.log)."""
    import os
    log_file = "logs/bot.log"
    if not os.path.exists(log_file):
        return {"logs": ["File log belum tersedia. Menunggu bot berjalan..."]}
    
    try:
        with open(log_file, "r") as f:
            lines = f.readlines()
            # Ambil 200 baris terakhir, dan hilangkan newline di akhir string
            return {"logs": [line.strip() for line in lines[-200:]]}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/notifications")
def get_notifications(token: str = Depends(verify_token)):
    """Mengambil notifikasi yang belum dibaca atau 20 notifikasi terbaru."""
    db = Session()
    try:
        from database import Notification
        
        # Ambil semua yang unread ATAU maksimal 20 terbaru jika sudah dibaca
        unread = db.query(Notification).filter_by(is_read=0).order_by(Notification.timestamp.desc()).all()
        if len(unread) < 10:
            latest = db.query(Notification).order_by(Notification.timestamp.desc()).limit(20).all()
            # Hindari duplikat
            seen_ids = set()
            combined = []
            for n in unread + latest:
                if n.id not in seen_ids:
                    combined.append(n)
                    seen_ids.add(n.id)
            notifications = sorted(combined, key=lambda x: x.timestamp, reverse=True)
        else:
            notifications = unread
            
        result = []
        for n in notifications:
            result.append({
                "id": n.id,
                "message": n.message,
                "type": n.type,
                "is_read": bool(n.is_read),
                "timestamp": n.timestamp.isoformat() if n.timestamp else None
            })
        return {"notifications": result}
    finally:
        db.close()

@app.post("/api/notifications/read")
def mark_notifications_read(token: str = Depends(verify_token)):
    """Menandai semua notifikasi sebagai sudah dibaca."""
    db = Session()
    try:
        from database import Notification
        db.query(Notification).filter_by(is_read=0).update({"is_read": 1})
        db.commit()
        return {"success": True}
    finally:
        db.close()
