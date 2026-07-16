from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import json
import os
import uuid
import jwt
from datetime import datetime, timedelta
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from typing import Optional
from pydantic import BaseModel
from database import init_db, BotState, TradeHistory, AppConfig, User, Notification

app = FastAPI(title="Indodax AutoTrade API (SaaS Edition)")

# Konfigurasi CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Session = init_db()
security = HTTPBearer()

JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-mixa-key-2026")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm="HS256")

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token tidak valid")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token kedaluwarsa")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token tidak valid")

@app.get("/")
def read_root():
    return {"message": "AutoTrade SaaS FastAPI Server is Running 🚀"}

class GoogleLoginRequest(BaseModel):
    credential: str

@app.post("/api/auth/google")
def google_login(req: GoogleLoginRequest):
    try:
        # Jika GOOGLE_CLIENT_ID kosong, lewati verifikasi audiens untuk sementara (Dev Mode)
        if not GOOGLE_CLIENT_ID:
            idinfo = id_token.verify_oauth2_token(req.credential, google_requests.Request())
        else:
            idinfo = id_token.verify_oauth2_token(req.credential, google_requests.Request(), GOOGLE_CLIENT_ID)
            
        email = idinfo['email']
        name = idinfo.get('name', '')
        picture = idinfo.get('picture', '')
        
        db = Session()
        try:
            user = db.query(User).filter_by(email=email).first()
            if not user:
                # User baru, beri trial 30 hari
                from database import get_wib_time
                trial_end = get_wib_time() + timedelta(days=30)
                user = User(email=email, name=name, picture=picture, trial_ends_at=trial_end)
                db.add(user)
                
                # Setup default config
                default_configs = [
                    AppConfig(user_id=email, key="GEMINI_MODEL", value="gemini-2.5-flash"),
                    AppConfig(user_id=email, key="AUTO_SCREENER_ENABLED", value="False")
                ]
                db.add_all(default_configs)
            else:
                user.name = name
                user.picture = picture
            db.commit()
            
            # Cek status berlangganan/trial
            from database import get_wib_time
            now = get_wib_time()
            has_access = False
            if user.subscription_ends_at and user.subscription_ends_at > now:
                has_access = True
            elif user.trial_ends_at and user.trial_ends_at > now:
                has_access = True
                
            token = create_access_token({"sub": email})
            return {
                "token": token,
                "user": {
                    "email": email,
                    "name": name,
                    "picture": picture,
                    "has_access": has_access,
                    "trial_ends_at": user.trial_ends_at.isoformat() if user.trial_ends_at else None,
                    "subscription_ends_at": user.subscription_ends_at.isoformat() if user.subscription_ends_at else None
                }
            }
        finally:
            db.close()
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"Token Google tidak valid: {e}")

class LoginRequest(BaseModel):
    password: str

@app.post("/api/login")
def login(req: LoginRequest):
    # Backward compatibility untuk admin login tanpa Google
    admin_password = os.getenv("ADMIN_PASSWORD", "mixa2026")
    if req.password != admin_password:
        raise HTTPException(status_code=401, detail="Password salah")
    
    token = create_access_token({"sub": "admin@mixa.ai"})
    return {"token": token, "user": {"email": "admin@mixa.ai", "name": "Admin", "has_access": True}}

class CoinAddRequest(BaseModel):
    symbol: str

@app.post("/api/coin")
def add_coin(req: CoinAddRequest, user_id: str = Depends(verify_token)):
    db = Session()
    try:
        symbol = req.symbol.upper().strip()
        if not symbol.endswith('/IDR'):
            symbol += '/IDR'
            
        existing = db.query(BotState).filter_by(user_id=user_id, symbol=symbol).first()
        if existing:
            if not existing.is_active:
                existing.is_active = 1
                db.commit()
                return {"message": f"Koin {symbol} diaktifkan kembali"}
            raise HTTPException(status_code=400, detail=f"Koin {symbol} sudah ada dan aktif")
            
        new_state = BotState(user_id=user_id, symbol=symbol, is_active=1, signal="HOLD", mode="AUTO")
        db.add(new_state)
        db.commit()
        return {"message": f"Koin {symbol} berhasil ditambahkan"}
    finally:
        db.close()

@app.delete("/api/coin/{symbol_path:path}")
def remove_coin(symbol_path: str, user_id: str = Depends(verify_token)):
    db = Session()
    try:
        symbol = symbol_path.replace('%2F', '/')
        existing = db.query(BotState).filter_by(user_id=user_id, symbol=symbol).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Koin tidak ditemukan")
            
        db.delete(existing)
        db.commit()
        return {"message": f"Koin {symbol} dihapus permanen"}
    finally:
        db.close()

@app.get("/api/status")
def get_bot_status(user_id: str = Depends(verify_token)):
    db = Session()
    try:
        from database import get_wib_time
        import os
        cooldown_hours = float(os.getenv('COOLDOWN_HOURS', 2.0))
        states = db.query(BotState).filter_by(user_id=user_id).all()
        result = []
        for state in states:
            cooldown_remaining_minutes = 0
            last_sell = db.query(TradeHistory).filter(TradeHistory.user_id == user_id, TradeHistory.symbol == state.symbol, TradeHistory.action == "SELL").order_by(TradeHistory.timestamp.desc()).first()
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
def get_trade_history(symbol_path: str, user_id: str = Depends(verify_token)):
    db = Session()
    try:
        history = db.query(TradeHistory).filter_by(user_id=user_id, symbol=symbol_path).order_by(TradeHistory.timestamp.desc()).all()
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
def get_chart_data(symbol_path: str, user_id: str = Depends(verify_token)):
    db = Session()
    try:
        state = db.query(BotState).filter_by(user_id=user_id, symbol=symbol_path).first()
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
    auto_screener_enabled: Optional[bool] = None
    max_active_coins: Optional[int] = None

@app.get("/api/config")
def get_config(user_id: str = Depends(verify_token)):
    db = Session()
    try:
        configs = db.query(AppConfig).filter_by(user_id=user_id).all()
        result = {
            "is_admin": user_id == "admin@mixa.ai",
            "gemini_model": "gemini-2.5-flash",
            "initial_balance": 0.0,
            "telegram_token": "",
            "telegram_chat_id": "",
            "indodax_api_key": "",
            "indodax_secret_key": "",
            "auto_screener_enabled": False,
            "max_active_coins": 5
        }
        for c in configs:
            if c.key == "GEMINI_MODEL": result["gemini_model"] = c.value
            elif c.key == "INITIAL_BALANCE": result["initial_balance"] = float(c.value) if c.value else 0.0
            elif c.key == "TELEGRAM_BOT_TOKEN" and user_id == "admin@mixa.ai": result["telegram_token"] = c.value
            elif c.key == "TELEGRAM_CHAT_ID": result["telegram_chat_id"] = c.value
            elif c.key == "INDODAX_API_KEY": result["indodax_api_key"] = c.value
            elif c.key == "INDODAX_SECRET_KEY": result["indodax_secret_key"] = c.value
            elif c.key == "AUTO_SCREENER_ENABLED": result["auto_screener_enabled"] = (c.value.lower() == 'true')
            elif c.key == "MAX_ACTIVE_COINS": result["max_active_coins"] = int(c.value) if c.value else 5
        return result
    finally:
        db.close()

@app.post("/api/config")
def update_config(data: ConfigUpdate, user_id: str = Depends(verify_token)):
    db = Session()
    try:
        def update_or_create(key, value):
            if value is not None:
                item = db.query(AppConfig).filter_by(user_id=user_id, key=key).first()
                if not item:
                    item = AppConfig(user_id=user_id, key=key, value=str(value))
                    db.add(item)
                else:
                    item.value = str(value)

        update_or_create("GEMINI_MODEL", data.gemini_model)
        update_or_create("INITIAL_BALANCE", data.initial_balance)
        if user_id == "admin@mixa.ai":
            update_or_create("TELEGRAM_BOT_TOKEN", data.telegram_token)
        update_or_create("TELEGRAM_CHAT_ID", data.telegram_chat_id)
        update_or_create("INDODAX_API_KEY", data.indodax_api_key)
        update_or_create("INDODAX_SECRET_KEY", data.indodax_secret_key)
        if data.auto_screener_enabled is not None:
            update_or_create("AUTO_SCREENER_ENABLED", str(data.auto_screener_enabled))
        if data.max_active_coins is not None:
            update_or_create("MAX_ACTIVE_COINS", str(data.max_active_coins))
        
        db.commit()
        return {"message": "Konfigurasi berhasil disimpan"}
    finally:
        db.close()

@app.get("/api/performance")
def get_performance(user_id: str = Depends(verify_token)):
    db = Session()
    try:
        trades = db.query(TradeHistory).filter(TradeHistory.user_id == user_id, TradeHistory.action == "SELL", TradeHistory.pnl_pct.isnot(None)).order_by(TradeHistory.timestamp.asc()).all()
        
        daily_pnl = {}
        for t in trades:
            date_str = t.timestamp.strftime("%Y-%m-%d")
            if date_str not in daily_pnl:
                daily_pnl[date_str] = {'date': date_str, 'total_pnl_pct': 0.0, 'trade_count': 0, 'win_count': 0}
            
            daily_pnl[date_str]['total_pnl_pct'] += t.pnl_pct
            daily_pnl[date_str]['trade_count'] += 1
            if t.pnl_pct > 0:
                daily_pnl[date_str]['win_count'] += 1
                
        daily_list = list(daily_pnl.values())
        
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
    telegram_chat_id: str

@app.post("/api/config/telegram_test")
def test_telegram(data: TelegramTest, user_id: str = Depends(verify_token)):
    if not data.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Chat ID harus diisi")
    db = Session()
    try:
        from notifier import TelegramNotifier
        test_notifier = TelegramNotifier()
        master_token, _ = test_notifier._get_credentials("admin@mixa.ai")
        
        if not master_token:
            raise HTTPException(status_code=400, detail="Admin belum mengkonfigurasi Bot Token Utama")
            
        import requests
        base_url = f"https://api.telegram.org/bot{master_token}/sendMessage"
        payload = {
            "chat_id": data.telegram_chat_id,
            "text": f"🟢 **Test Ping dari MIXA AI (SaaS)**\nHalo {user_id}! Koneksi Telegram Anda berhasil terhubung dengan Dasbor!",
            "parse_mode": "Markdown"
        }
        res = requests.post(base_url, json=payload, timeout=5)
        if not res.ok:
            raise HTTPException(status_code=400, detail=f"Gagal mengirim pesan: {res.text}")
            
        return {"message": "Test message sent successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

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
def run_backtest(req: BacktestRequest, user_id: str = Depends(verify_token)):
    # Logika backtest dibiarkan sama karena tidak mengubah database state
    try:
        from exchange_handler import IndodaxHandler
        handler = IndodaxHandler(api_key="", secret_key="", dry_run=True)
        symbol_api = req.symbol.replace("/", "")
        
        df = handler.fetch_hidden_ohlcv(symbol=symbol_api, tf=req.timeframe, limit=1000)
        if df.empty or len(df) < 60:
            raise HTTPException(status_code=400, detail="Gagal menarik data atau data terlalu sedikit")
            
        from strategy import MovingAverageStrategy, RSIBreakoutStrategy, BollingerBandsStrategy, GridTradingStrategy
        if req.strategy == "RSI Breakout":
            strat = RSIBreakoutStrategy()
        elif req.strategy == "Bollinger Bands":
            strat = BollingerBandsStrategy()
        elif req.strategy == "Grid Trading":
            strat = GridTradingStrategy()
        else:
            strat = MovingAverageStrategy()
            
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
            
            if coin_held > 0 and req.use_trailing_stop:
                if current_price > highest_price:
                    highest_price = current_price
                drop_pct = ((highest_price - current_price) / highest_price) * 100
                if drop_pct >= req.trailing_stop_pct:
                    signal = "SELL"
                    
            if coin_held > 0 and signal != "SELL" and req.use_dca and dca_count < req.dca_max_orders:
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                drop_threshold = req.dca_step_pct * (dca_count + 1)
                if pnl_pct <= -drop_threshold:
                    dca_amount = float(balance * 0.5) 
                    if dca_amount > 10000:
                        balance -= dca_amount
                        total_invested += dca_amount
                        coin_held += float(dca_amount / current_price)
                        entry_price = float(total_invested / coin_held)
                        highest_price = entry_price
                        dca_count += 1
                        trades.append({"time": str(timestamp), "type": f"DCA #{dca_count}", "price": current_price, "amount": dca_amount, "pnl": None})
                        
            if signal == "BUY" and coin_held == 0:
                buy_amount = float(balance) 
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
def update_bot_config(symbol_path: str, config: BotConfigUpdate, user_id: str = Depends(verify_token)):
    db = Session()
    try:
        state = db.query(BotState).filter_by(user_id=user_id, symbol=symbol_path).first()
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
            state.total_idr_invested = 0.0
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
def get_system_logs(user_id: str = Depends(verify_token)):
    # Logs masih global karena ditulis ke file fisik
    import os
    log_file = "logs/bot.log"
    if not os.path.exists(log_file):
        return {"logs": ["File log belum tersedia. Menunggu bot berjalan..."]}
    try:
        with open(log_file, "r") as f:
            lines = f.readlines()
            return {"logs": [line.strip() for line in lines[-200:]]}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/notifications")
def get_notifications(user_id: str = Depends(verify_token)):
    db = Session()
    try:
        from database import Notification
        unread = db.query(Notification).filter_by(user_id=user_id, is_read=0).order_by(Notification.timestamp.desc()).all()
        if len(unread) < 10:
            latest = db.query(Notification).filter_by(user_id=user_id).order_by(Notification.timestamp.desc()).limit(20).all()
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
def mark_notifications_read(user_id: str = Depends(verify_token)):
    db = Session()
    try:
        from database import Notification
        db.query(Notification).filter_by(user_id=user_id, is_read=0).update({"is_read": 1})
        db.commit()
        return {"success": True}
    finally:
        db.close()

class ExtendSubRequest(BaseModel):
    email: str
    days: int

@app.get("/api/admin/users")
def get_all_users(user_id: str = Depends(verify_token)):
    if user_id != "admin@mixa.ai":
        raise HTTPException(status_code=403, detail="Akses Ditolak: Hanya Admin")
    db = Session()
    try:
        users = db.query(User).all()
        result = []
        for u in users:
            result.append({
                "email": u.email,
                "name": u.name,
                "picture": u.picture,
                "trial_ends_at": u.trial_ends_at.isoformat() if u.trial_ends_at else None,
                "subscription_ends_at": u.subscription_ends_at.isoformat() if u.subscription_ends_at else None
            })
        return result
    finally:
        db.close()

@app.post("/api/admin/extend-sub")
def extend_subscription(req: ExtendSubRequest, user_id: str = Depends(verify_token)):
    if user_id != "admin@mixa.ai":
        raise HTTPException(status_code=403, detail="Akses Ditolak: Hanya Admin")
    db = Session()
    try:
        from database import get_wib_time
        now = get_wib_time()
        user = db.query(User).filter_by(email=req.email).first()
        if not user:
            raise HTTPException(status_code=404, detail="User tidak ditemukan")
        
        current_end = user.subscription_ends_at or user.trial_ends_at or now
        if current_end < now:
            current_end = now
            
        new_end = current_end + timedelta(days=req.days)
        user.subscription_ends_at = new_end
        db.commit()
        return {"message": f"Masa aktif diperpanjang hingga {new_end.strftime('%d %b %Y')}"}
    finally:
        db.close()

@app.get("/api/admin/dashboard")
def get_admin_dashboard(user_id: str = Depends(verify_token)):
    if user_id != "admin@mixa.ai":
        raise HTTPException(status_code=403, detail="Akses Ditolak: Hanya Admin")
    
    db = Session()
    try:
        from sqlalchemy import func
        total_users = db.query(User).count()
        
        active_users = db.query(BotState.user_id).filter(BotState.is_active == 1).distinct().count()
        
        all_trades = db.query(TradeHistory).all()
        total_volume = 0.0
        
        user_pnl = {}
        
        for trade in all_trades:
            if trade.nominal:
                val_str = trade.nominal.replace('Rp', '').replace(',', '').strip()
                # Handle cases where nominal is "0.001 BTC"
                if ' ' in val_str:
                    val_str = val_str.split(' ')[0]
                try:
                    vol = float(val_str)
                    # if it's too small, maybe it was asset amount instead of IDR, ignore for volume if < 1000? 
                    # well, total_volume is an approximation
                    total_volume += vol
                except ValueError:
                    pass
                    
            if trade.pnl_pct is not None:
                uid = trade.user_id
                if uid not in user_pnl:
                    user_pnl[uid] = {'pnl_sum': 0.0, 'trade_count': 0, 'email': uid}
                user_pnl[uid]['pnl_sum'] += trade.pnl_pct
                user_pnl[uid]['trade_count'] += 1
                
        leaderboard = []
        for uid, data in user_pnl.items():
            if data['trade_count'] > 0:
                avg_pnl = data['pnl_sum']
                u_obj = db.query(User).filter_by(email=uid).first()
                name = u_obj.name if u_obj and u_obj.name else uid.split('@')[0]
                leaderboard.append({
                    "email": uid,
                    "name": name,
                    "total_pnl_pct": avg_pnl,
                    "trade_count": data['trade_count']
                })
        
        leaderboard.sort(key=lambda x: x['total_pnl_pct'], reverse=True)
        top_10 = leaderboard[:10]
        
        try:
            import psutil
            cpu_usage = psutil.cpu_percent(interval=0.1)
            ram_usage = psutil.virtual_memory().percent
        except ImportError:
            cpu_usage = 0.0
            ram_usage = 0.0
            
        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_volume": total_volume,
            "leaderboard": top_10,
            "server": {
                "cpu": cpu_usage,
                "ram": ram_usage
            }
        }
    finally:
        db.close()
