import os
import time
import json
import logging
import random
import concurrent.futures
from datetime import datetime
from dotenv import load_dotenv

from exchange_handler import IndodaxHandler
from strategy import MovingAverageStrategy, RSIBreakoutStrategy, BollingerBandsStrategy, GridTradingStrategy
from database import init_db, BotState, TradeHistory, AppConfig, Notification
from news_scraper import NewsScraper
from screener import fetch_trending_tickers, run_auto_screener_for_user
from notifier import TelegramNotifier
from mixa_ai import MixaAI

# Konfigurasi Catatan (Logging) agar tercetak di layar dan di file
os.makedirs("logs", exist_ok=True)
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("logs/bot.log"), logging.StreamHandler()])

# === GLOBAL RESOURCES ===
Session = None
mixa = None
notifier = None
scraper = None
COOLDOWN_HOURS = 2.0
DRY_RUN = True
status_mode = "SIMULASI (DRY RUN)"

# === MEMORI SEMENTARA (RAM) (Thread-Safe under GIL) ===
last_buy_times = {}
last_mixa_times = {}
last_signals = {}
last_sell_times = {}
last_ai_eval_times = {}
latest_news = []

def get_memory_key(user_id, symbol):
    """Menghasilkan kunci unik (User + Koin) untuk memori cache."""
    return f"{user_id}_{symbol}"

def process_coin_for_user(user_id, symbol_indodax):
    """Fungsi Pekerja Tunggal yang memproses satu koin untuk satu user (Thread)."""
    # 1. Jeda Acak (Anti-Spam Indodax Rate Limit)
    time.sleep(random.uniform(0.1, 3.0))
    
    db_session = Session()
    try:
        mem_key = get_memory_key(user_id, symbol_indodax)
        
        # Inisialisasi memori jika belum ada
        if mem_key not in last_signals:
            last_signals[mem_key] = "HOLD"
            last_sell_times[mem_key] = 0.0
            last_mixa_times[mem_key] = time.time() - 900
            last_ai_eval_times[mem_key] = 0.0
            
        koin_utama = symbol_indodax.split('/')[0] # 'BTC'
        api_symbol = symbol_indodax.replace('/', '') # 'BTCIDR'
        
        # 2. Ambil State User
        state = db_session.query(BotState).filter_by(user_id=user_id, symbol=symbol_indodax).first()
        if not state or state.is_active != 1:
            return # Koin sudah tidak aktif, abaikan
            
        # 3. Ambil API Key Spesifik milik User
        api_conf = db_session.query(AppConfig).filter_by(user_id=user_id, key="INDODAX_API_KEY").first()
        sec_conf = db_session.query(AppConfig).filter_by(user_id=user_id, key="INDODAX_SECRET_KEY").first()
        
        if not api_conf or not sec_conf or not api_conf.value or not sec_conf.value:
            logging.warning(f"[{user_id}] [{symbol_indodax}] API Key belum diisi. Trading diabaikan.")
            return
            
        indodax_executor = IndodaxHandler(api_key=api_conf.value, secret_key=sec_conf.value, dry_run=DRY_RUN)
        
        coin_tp_pct = state.take_profit_pct
        coin_sl_pct = state.stop_loss_pct
        coin_buy_amount = state.buy_amount
        
        # ==== PHASE 4: AUTOPILOT AI ====
        if getattr(state, 'use_autotune', 0) == 1:
            current_time = time.time()
            last_autotune = getattr(state, 'last_autotune_time', 0.0)
            if current_time - last_autotune > 4 * 3600:
                logging.info(f"[{user_id}] [{symbol_indodax}] Memulai Evaluasi Autopilot (Tiap 4 Jam)...")
                df_4h = indodax_executor.fetch_hidden_ohlcv(api_symbol, tf="240", limit=210)
                if not df_4h.empty and len(df_4h) >= 200:
                    df_4h['tr0'] = abs(df_4h['high'] - df_4h['low'])
                    df_4h['tr1'] = abs(df_4h['high'] - df_4h['close'].shift())
                    df_4h['tr2'] = abs(df_4h['low'] - df_4h['close'].shift())
                    df_4h['tr'] = df_4h[['tr0', 'tr1', 'tr2']].max(axis=1)
                    atr = df_4h['tr'].rolling(window=14).mean().iloc[-1]
                    
                    sma_50 = df_4h['close'].rolling(window=50).mean().iloc[-1]
                    sma_200 = df_4h['close'].rolling(window=200).mean().iloc[-1]
                    price = float(df_4h.iloc[-1]['close'])
                    
                    atr_pct = (atr / price) * 100
                    
                    new_strategy = state.strategy
                    new_dca = getattr(state, 'use_dca', 0)
                    new_tp = state.take_profit_pct
                    new_sl = state.stop_loss_pct
                    new_ts = getattr(state, 'use_trailing_stop', 0)
                    new_droi = getattr(state, 'use_dynamic_roi', 0)
                    new_wr = getattr(state, 'use_whale_radar', 0)
                    new_tb = getattr(state, 'use_trailing_buy', 0)
                    note = ""
                    
                    if price < sma_200:
                        new_strategy, new_dca, new_tp, new_sl, new_ts, new_droi, new_wr, new_tb = "RSI Breakout", 0, 3.0, 3.0, 1, 0, 1, 0
                        note = "BEAR MARKET: Beralih ke RSI Breakout & Menyesuaikan semua Manajemen Risiko (Defensif)."
                    elif atr_pct < 1.0:
                        new_strategy, new_dca, new_tp, new_sl, new_ts, new_droi, new_wr, new_tb = "Bollinger Bands", 1, 1.5, 1.5, 0, 1, 0, 1
                        note = f"SIDEWAYS: Volatilitas ({atr_pct:.2f}%) rendah. Beralih ke Bollinger Bands (Scalping)."
                    elif price > sma_50:
                        new_strategy, new_dca, new_tp, new_sl, new_ts, new_droi, new_wr, new_tb = "MA Crossover", 1, 10.0, 5.0, 1, 1, 1, 1
                        note = "BULL MARKET: Beralih ke MA Crossover & Menyesuaikan Manajemen Risiko (Agresif)."
                    
                    if note and (new_strategy != state.strategy or new_tp != state.take_profit_pct):
                        state.strategy = new_strategy
                        state.use_dca = new_dca
                        state.take_profit_pct = new_tp
                        state.stop_loss_pct = new_sl
                        state.use_trailing_stop = new_ts
                        state.use_dynamic_roi = new_droi
                        state.use_whale_radar = new_wr
                        state.use_trailing_buy = new_tb
                        
                        notif = Notification(user_id=user_id, message=f"[{symbol_indodax}] AUTOPILOT: {note}", type="warning" if "BEAR" in note else "success" if "BULL" in note else "info")
                        db_session.add(notif)
                        logging.info(f"[{user_id}] [{symbol_indodax}] {note}")
                        
                    state.last_autotune_time = current_time
                    db_session.commit()
        
        logging.info(f"[{user_id}] [{symbol_indodax}] Mengambil grafik dari API Indodax...")
        df = indodax_executor.fetch_hidden_ohlcv(api_symbol, tf="15", limit=200)
        
        if df.empty:
            logging.warning(f"[{user_id}] [{symbol_indodax}] Gagal menarik grafik.")
            return
            
        current_price_idr = float(df.iloc[-1]['close'])
        
        # ==== DYNAMIC STRATEGY ROUTING ====
        if state.strategy == "Gemini AI":
            current_time = time.time()
            if current_time - last_ai_eval_times[mem_key] >= 900: # Evaluasi tiap 15 menit
                config_model = db_session.query(AppConfig).filter_by(user_id=user_id, key="GEMINI_MODEL").first()
                model_name = config_model.value if config_model else "gemini-2.5-flash"
                current_pos = (state.entry_price or 0.0) > 0
                ai_result = mixa.get_ai_trading_signal(df, current_pos, model_name=model_name, news=latest_news)
                signal = ai_result.get('signal', 'HOLD')
                state.mixa_insight = f"[{signal}] {ai_result.get('reason', '')}"
                last_ai_eval_times[mem_key] = current_time
                db_session.commit()
            else:
                signal = "HOLD"
                
            # Fallback jika terjadi force sell oleh sistem lain (contoh: trailing stop nanti)
        else:
            if state.strategy == "RSI Breakout": strategy = RSIBreakoutStrategy(period=14)
            elif state.strategy == "Bollinger Bands": strategy = BollingerBandsStrategy(period=20)
            elif state.strategy == "Grid Trading": strategy = GridTradingStrategy(period=20)
            else: strategy = MovingAverageStrategy(fast_period=10, slow_period=50)
                
            signal = strategy.analyze(df)
        
        # ==== PHASE 1: MACRO TREND FILTER (4H) ====
        if signal == "BUY" and getattr(state, 'use_macro_trend', 0) == 1:
            try:
                df_4h = indodax_executor.fetch_hidden_ohlcv(api_symbol, tf="240", limit=60)
                if not df_4h.empty and len(df_4h) >= 50:
                    sma_50_4h = df_4h['close'].rolling(window=50).mean().iloc[-1]
                    if current_price_idr < sma_50_4h:
                        logging.warning(f"[{user_id}] [{symbol_indodax}] Tren Makro Bearish. Sinyal BUY dibatalkan (Fakeout dicegah)!")
                        signal = "HOLD"
            except Exception as e:
                pass
                
        # ==== PHASE 3: WHALE RADAR (ORDERBOOK) ====
        if signal == "BUY" and getattr(state, 'use_whale_radar', 0) == 1:
            try:
                imbalance = indodax_executor.get_orderbook_imbalance(symbol_indodax, depth_pct=2.0)
                if imbalance['ratio'] >= 3.0:
                    logging.warning(f"[{user_id}] [{symbol_indodax}] WHALE RADAR ALERT! Tembok Jual {imbalance['ratio']:.1f}x. BUY ditahan.")
                    signal = "HOLD"
            except Exception:
                pass
                
        # ==== PHASE 2: TRAILING BUY ====
        if getattr(state, 'use_trailing_buy', 0) == 1 and (state.entry_price or 0.0) == 0.0:
            is_active = getattr(state, 'trailing_buy_active', 0) == 1
            lowest_price = getattr(state, 'trailing_buy_lowest_price', 0.0)
            bounce_pct = getattr(state, 'trailing_buy_pct', 1.0)
            
            if signal == "SELL" and is_active:
                state.trailing_buy_active, state.trailing_buy_lowest_price = 0, 0.0
            elif signal == "BUY" and not is_active:
                state.trailing_buy_active, state.trailing_buy_lowest_price, signal = 1, current_price_idr, "HOLD"
            elif is_active:
                if current_price_idr < lowest_price:
                    state.trailing_buy_lowest_price, signal = current_price_idr, "HOLD"
                else:
                    bounce_threshold = lowest_price * (1 + (bounce_pct / 100.0))
                    if current_price_idr >= bounce_threshold:
                        state.trailing_buy_active, state.trailing_buy_lowest_price, signal = 0, 0.0, "BUY"
                    else:
                        signal = "HOLD"

        # ==== RISK MANAGEMENT (TP/SL) ====
        if (state.entry_price or 0.0) > 0 and (state.total_idr_invested or 0.0) == 0.0:
            asset_bal_sync = indodax_executor.get_balance().get(koin_utama, 0)
            if asset_bal_sync > 0: state.total_idr_invested = asset_bal_sync * state.entry_price
                
        entry_price = state.entry_price or 0.0
        if entry_price > 0:
            highest_price = state.highest_price_since_buy or 0.0
            if current_price_idr > highest_price:
                state.highest_price_since_buy = current_price_idr
                highest_price = current_price_idr
                
            pnl_pct = ((current_price_idr - entry_price) / entry_price) * 100
            
            # Dynamic ROI
            dynamic_target_pct = coin_tp_pct
            if state.use_dynamic_roi and state.dynamic_roi_config and getattr(state, 'last_buy_time', 0):
                try:
                    roi_rules = json.loads(state.dynamic_roi_config)
                    minutes_held = (time.time() - state.last_buy_time) / 60.0
                    for min_str in sorted(roi_rules.keys(), key=int, reverse=True):
                        if minutes_held >= int(min_str):
                            dynamic_target_pct = float(roi_rules[min_str])
                            break
                    if pnl_pct >= dynamic_target_pct: signal = "SELL"
                except:
                    pass
            
            # DCA / Safety Orders
            if signal != "SELL" and state.use_dca:
                dca_count = state.dca_completed_orders or 0
                max_orders = state.dca_max_orders or 3
                if dca_count < max_orders:
                    step_pct = state.dca_step_pct or 3.0
                    drop_threshold = step_pct * (dca_count + 1)
                    
                    if pnl_pct <= -drop_threshold:
                        volume_scale = state.dca_volume_scale or 1.0
                        dca_amount = coin_buy_amount * (volume_scale ** dca_count)
                        idr_bal_dca = indodax_executor.get_balance().get('IDR', 0)
                        
                        if idr_bal_dca >= dca_amount or DRY_RUN:
                            order = indodax_executor.place_buy_order(symbol_indodax, dca_amount)
                            if order:
                                msg = f"[{user_id}] 🛒 **DCA / SAFETY ORDER!**\nTarget: {symbol_indodax}\nTahap: #{dca_count+1}\nNominal: Rp {dca_amount:,.0f}"
                                notifier.send_message(user_id, msg)
                                state.total_idr_invested = (state.total_idr_invested or 0.0) + dca_amount
                                state.dca_completed_orders = dca_count + 1
                                
                                time.sleep(2)
                                new_asset_bal = indodax_executor.get_balance().get(koin_utama, 0)
                                if new_asset_bal > 0:
                                    new_avg_price = state.total_idr_invested / new_asset_bal
                                    state.entry_price, state.highest_price_since_buy = new_avg_price, new_avg_price
                                    
                                db_session.add(TradeHistory(user_id=user_id, symbol=symbol_indodax, action=f"BUY (DCA {dca_count+1})", price=current_price_idr, nominal=f"Rp {dca_amount:,.0f}"))
                                db_session.commit()
            
            # Trailing Stop Loss
            if signal != "SELL" and getattr(state, 'use_trailing_stop', 0):
                if highest_price > 0:
                    if ((highest_price - current_price_idr) / highest_price) * 100 >= (state.trailing_stop_pct or 2.0):
                        signal = "SELL"
            
            # Fixed TP/SL
            if signal != "SELL":
                if pnl_pct <= -coin_sl_pct: signal = "SELL"
                elif not getattr(state, 'use_dynamic_roi', 0) and pnl_pct >= coin_tp_pct: signal = "SELL"
        
        # Cooldown Logic
        if signal == "BUY" and (time.time() - last_sell_times[mem_key]) < (COOLDOWN_HOURS * 3600):
            signal = "HOLD"

        logging.info(f"[{user_id}] [{symbol_indodax}] Harga: Rp {current_price_idr:,.0f} | Sinyal: {signal}")
        
        # Eksekusi Beli / Jual
        balances = indodax_executor.get_balance()
        idr_bal, asset_bal = balances.get('IDR', 0), balances.get(koin_utama, 0)
        estimated_value_idr = asset_bal * current_price_idr
        
        if estimated_value_idr < 1000 and (state.entry_price or 0.0) > 0:
            if not indodax_executor.has_open_orders(symbol_indodax):
                state.entry_price, state.highest_price_since_buy, state.last_buy_time, state.total_idr_invested, state.dca_completed_orders = 0.0, 0.0, 0.0, 0.0, 0
                db_session.commit()

        if signal == "BUY" and last_signals[mem_key] != "BUY":
            if idr_bal >= coin_buy_amount or DRY_RUN:
                indodax_executor.cancel_all_open_orders(symbol_indodax)
                time.sleep(1)
                if indodax_executor.place_buy_order(symbol_indodax, coin_buy_amount):
                    notifier.send_message(user_id, f"[{user_id}] 🟢 **SINYAL BELI!**\nTarget: {symbol_indodax}\nNominal: Rp {coin_buy_amount:,.0f}")
                    last_signals[mem_key] = "BUY"
                    state.entry_price = current_price_idr
                    state.highest_price_since_buy = current_price_idr
                    state.last_buy_time = time.time()
                    state.total_idr_invested = coin_buy_amount
                    state.dca_completed_orders = 0
                    db_session.add(TradeHistory(user_id=user_id, symbol=symbol_indodax, action="BUY", price=current_price_idr, nominal=f"Rp {coin_buy_amount:,.0f}"))
            else:
                last_signals[mem_key] = "BUY" # Bungkam agar tidak spam API
                
        elif signal == "SELL" and last_signals[mem_key] != "SELL":
            if estimated_value_idr >= 10000 or DRY_RUN:
                indodax_executor.cancel_all_open_orders(symbol_indodax)
                time.sleep(1)
                asset_bal = indodax_executor.get_balance().get(koin_utama, 0)
                amount_to_sell = 0.001 if DRY_RUN else asset_bal 
                
                if indodax_executor.place_sell_order(symbol_indodax, amount_to_sell):
                    realized_pnl = ((current_price_idr - (state.entry_price or 0.0)) / (state.entry_price or 1.0)) * 100 if (state.entry_price or 0.0) > 0 else 0
                    notifier.send_message(user_id, f"[{user_id}] 🔴 **SINYAL JUAL!**\nTarget: {symbol_indodax}\nHasil PnL: {realized_pnl:.2f}%")
                    last_signals[mem_key] = "SELL"
                    state.entry_price, state.highest_price_since_buy, state.last_buy_time, state.total_idr_invested, state.dca_completed_orders = 0.0, 0.0, 0.0, 0.0, 0
                    last_sell_times[mem_key] = time.time()
                    db_session.add(TradeHistory(user_id=user_id, symbol=symbol_indodax, action="SELL", price=current_price_idr, nominal=f"{amount_to_sell} {koin_utama}", pnl_pct=realized_pnl))
            else:
                last_signals[mem_key] = "SELL" # Bungkam spam

        # Mixa AI Analysis
        current_time = time.time()
        rsi_val = float(df.iloc[-1]['RSI_14']) if 'RSI_14' in df.columns else 50.0
        
        if current_time - last_mixa_times[mem_key] >= 900:
            config_model = db_session.query(AppConfig).filter_by(user_id=user_id, key="GEMINI_MODEL").first()
            model_name = config_model.value if config_model else "gemini-2.5-flash"
            state.mixa_insight = mixa.get_market_insight(current_price_idr, signal, rsi_val, model_name=model_name, news=latest_news)
            last_mixa_times[mem_key] = current_time
            
        if not getattr(state, 'mixa_insight', None):
            state.mixa_insight = "Menunggu inisialisasi AI..."

        df_history = df.tail(50).copy()
        df_history = df_history.assign(timestamp=df_history['timestamp'].astype(str))
        
        state.current_price = current_price_idr
        state.signal = signal
        state.mode = status_mode
        state.balances = json.dumps(balances)
        state.chart_data = df_history.to_json(orient='records')
        
        db_session.commit()
    
    except Exception as e:
        logging.error(f"Error di thread koin {symbol_indodax} milik {user_id}: {e}")
    finally:
        db_session.close()

def main():
    global Session, mixa, notifier, scraper, COOLDOWN_HOURS, DRY_RUN, status_mode, latest_news
    
    load_dotenv()
    DRY_RUN = os.getenv('DRY_RUN', 'True').lower() in ('true', '1', 't')
    COOLDOWN_HOURS = float(os.getenv('COOLDOWN_HOURS', 2.0))
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

    Session = init_db()
    notifier = TelegramNotifier(token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID)
    mixa = MixaAI()
    scraper = NewsScraper()
    
    status_mode = 'SIMULASI (DRY RUN)' if DRY_RUN else 'RIIL (UANG ASLI)'
    logging.info(f"Bot Multi-Tenant Multi-Thread Dimulai. Mode: {status_mode}")
    notifier.send_message("admin@mixa.ai", f"🚀 **Bot Mesin Multi-Tugas Aktif**\nMode: {status_mode}")

    last_news_time = 0
    last_screener_time = 0
    dummy_executor = IndodaxHandler(api_key="", secret_key="", dry_run=True)
    
    while True:
        try:
            current_time = time.time()
            if current_time - last_news_time > 1800:
                logging.info("Memperbarui berita global...")
                latest_news = scraper.fetch_latest_news(limit=5)
                last_news_time = current_time
                
            if current_time - last_screener_time > 3600:
                logging.info("--- [GLOBAL SCREENER] Memulai Evaluasi Portofolio Otomatis ---")
                top_volume = fetch_trending_tickers(dummy_executor)
                if top_volume:
                    db_sess = Session()
                    try:
                        from database import User, get_wib_time
                        now = get_wib_time()
                        screener_configs = db_sess.query(AppConfig).filter_by(key="AUTO_SCREENER_ENABLED", value="True").all()
                        for conf in screener_configs:
                            user_id = conf.user_id
                            max_c_conf = db_sess.query(AppConfig).filter_by(user_id=user_id, key="MAX_ACTIVE_COINS").first()
                            max_coins = int(max_c_conf.value) if max_c_conf else 5
                            
                            has_access = False
                            if user_id == "admin@mixa.ai":
                                has_access = True
                            else:
                                user_db = db_sess.query(User).filter_by(email=user_id).first()
                                if user_db:
                                    if user_db.subscription_ends_at and user_db.subscription_ends_at > now: has_access = True
                                    elif user_db.trial_ends_at and user_db.trial_ends_at > now: has_access = True
                                    
                            if has_access:
                                api_conf = db_sess.query(AppConfig).filter_by(user_id=user_id, key="INDODAX_API_KEY").first()
                                sec_conf = db_sess.query(AppConfig).filter_by(user_id=user_id, key="INDODAX_SECRET_KEY").first()
                                if api_conf and sec_conf and api_conf.value and sec_conf.value:
                                    user_executor = IndodaxHandler(api_key=api_conf.value, secret_key=sec_conf.value, dry_run=DRY_RUN)
                                    run_auto_screener_for_user(user_id, user_executor, db_sess, top_volume, max_coins)
                    except Exception as e:
                        logging.error(f"Screener Error: {e}")
                    finally:
                        db_sess.close()
                last_screener_time = current_time
                
            db_session = Session()
            try:
                from database import User, get_wib_time
                now = get_wib_time()
                # Dapatkan semua koin aktif, lalu saring berdasarkan masa aktif user
                active_states = db_session.query(BotState).filter_by(is_active=1).all()
                tasks = []
                for state in active_states:
                    if state.user_id == "admin@mixa.ai":
                        tasks.append((state.user_id, state.symbol))
                        continue
                        
                    user = db_session.query(User).filter_by(email=state.user_id).first()
                    if user:
                        has_access = False
                        if user.subscription_ends_at and user.subscription_ends_at > now:
                            has_access = True
                        elif user.trial_ends_at and user.trial_ends_at > now:
                            has_access = True
                            
                        if has_access:
                            tasks.append((state.user_id, state.symbol))
                        else:
                            logging.warning(f"[{state.user_id}] Masa aktif habis! Operasi koin {state.symbol} ditangguhkan.")
            finally:
                db_session.close()
                
            if not tasks:
                logging.info("Tidak ada koin aktif dari user manapun. Rehat 10 detik...")
                time.sleep(10)
                continue
                
            logging.info(f"--- Memulai Eksekusi Paralel untuk {len(tasks)} Koin Aktif ---")
            
            # Gunakan ThreadPoolExecutor dengan batas thread maksimum 20
            # (VPS RAM 4GB dan 2 vCPU mampu menangani ini dengan sangat santai, I/O bound)
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = [executor.submit(process_coin_for_user, user_id, symbol) for user_id, symbol in tasks]
                concurrent.futures.wait(futures)
                
            logging.info("Satu putaran paralel selesai. Menunggu 60 detik...\n")
            time.sleep(60)
            
        except Exception as e:
            logging.error(f"Terjadi kesalahan parah pada Main Loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
