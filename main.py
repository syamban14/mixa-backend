import os
import time
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

from exchange_handler import IndodaxHandler
from strategy import MovingAverageStrategy, RSIBreakoutStrategy, BollingerBandsStrategy
from notifier import TelegramNotifier
from mixa_ai import MixaAI
from database import init_db, BotState, TradeHistory, AppConfig

# Konfigurasi Catatan (Logging) agar tercetak di layar dan di file
os.makedirs("logs", exist_ok=True)
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("logs/bot.log"), logging.StreamHandler()])

def main():
    # 1. Muat pengaturan rahasia dari file .env
    load_dotenv()
    
    API_KEY = os.getenv('INDODAX_API_KEY')
    SECRET_KEY = os.getenv('INDODAX_SECRET_KEY')
    
    DRY_RUN = os.getenv('DRY_RUN', 'True').lower() in ('true', '1', 't')
    
    # Konfigurasi Anti-Spam
    COOLDOWN_HOURS = float(os.getenv('COOLDOWN_HOURS', 2.0))
    
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

    # 2. Inisialisasi Modul & Database
    indodax_executor = IndodaxHandler(api_key=API_KEY, secret_key=SECRET_KEY, dry_run=DRY_RUN)
    notifier = TelegramNotifier(token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID)
    mixa = MixaAI()
    
    # Inisialisasi Database (SQLite Engine)
    Session = init_db()
    
    status_mode = 'SIMULASI (DRY RUN)' if DRY_RUN else 'RIIL (UANG ASLI)'
    logging.info(f"Bot Multi-Koin dimulai. Mode: {status_mode}")
    
    # === SEEDING DEFAULT COINS ===
    ALL_SUPPORTED_COINS = ["BTC/IDR", "ETH/IDR", "SOL/IDR", "USDT/IDR", "XRP/IDR", "LRC/IDR", "DOGE/IDR", "PEPE/IDR"]
    try:
        db_session_init = Session()
        
        # 1. Hapus koin usang dari Database agar tidak muncul di Frontend
        existing_states = db_session_init.query(BotState).all()
        for state in existing_states:
            if state.symbol not in ALL_SUPPORTED_COINS:
                logging.info(f"Menghapus koin usang dari database: {state.symbol}")
                db_session_init.delete(state)
                
        # 2. Tambahkan koin baru jika belum ada
        for symbol in ALL_SUPPORTED_COINS:
            state = db_session_init.query(BotState).filter_by(symbol=symbol).first()
            if not state:
                state = BotState(symbol=symbol, is_active=1)
                db_session_init.add(state)
        db_session_init.commit()
    except Exception as e:
        logging.error(f"Gagal seeding koin awal: {e}")
    finally:
        db_session_init.close()
        
    notifier.send_message(f"🚀 **Bot Multi-Koin Aktif**\nMode: {status_mode}\nSistem Koin Dinamis Aktif")

    # === MEMORI SEMENTARA (RAM) ===
    # Kita menggunakan ALL_SUPPORTED_COINS karena kita sudah memastikan Database sinkron
    last_signals = {coin: "HOLD" for coin in ALL_SUPPORTED_COINS}
    last_sell_times = {coin: 0.0 for coin in ALL_SUPPORTED_COINS}
    
    # Staggering: Koin 1 langsung panggil AI, Koin 2 tunggu 3 menit, Koin 3 tunggu 6 menit, dst.
    current_t = time.time()
    last_mixa_times = {coin: current_t - 900 + (i * 180) for i, coin in enumerate(ALL_SUPPORTED_COINS)}

    # (entry_prices dictionary sudah dihapus karena kita menggunakan state.entry_price langsung dari DB)
    
    # 3. Looping Utama Bot
    while True:
        try:
            db_session = Session()
            
            # Ambil HANYA koin yang status is_active = 1 dari Database (Dinamis)
            active_states = db_session.query(BotState).filter_by(is_active=1).all()
            active_coins = [state.symbol for state in active_states]
            
            if not active_coins:
                logging.info("Tidak ada koin aktif yang dipantau saat ini. Menunggu 10 detik...")
                time.sleep(10)
                db_session.close()
                continue
                
            logging.info(f"--- Memulai Putaran untuk {len(active_coins)} Koin Aktif ---")
            
            # Putaran untuk setiap koin aktif
            for symbol_indodax in active_coins:
                koin_utama = symbol_indodax.split('/')[0] # 'BTC'
                api_symbol = symbol_indodax.replace('/', '') # 'BTCIDR'
                
                
                # Ambil State & Konfigurasi dari Database (TP, SL, Strategy)
                state = db_session.query(BotState).filter_by(symbol=symbol_indodax).first()
                if not state:
                    continue
                    
                coin_tp_pct = state.take_profit_pct
                coin_sl_pct = state.stop_loss_pct
                coin_buy_amount = state.buy_amount
                
                # Pastikan memori diinisialisasi untuk koin ini (mencegah KeyError)
                if symbol_indodax not in last_signals:
                    last_signals[symbol_indodax] = "HOLD"
                    last_sell_times[symbol_indodax] = 0.0
                    last_mixa_times[symbol_indodax] = time.time() - 900
                
                logging.info(f"[{symbol_indodax}] Mengambil grafik dari API Rahasia Indodax...")
                df = indodax_executor.fetch_hidden_ohlcv(api_symbol, tf="15", limit=200)
                
                if df.empty:
                    logging.warning(f"[{symbol_indodax}] Gagal menarik grafik. Lanjut ke koin berikutnya.")
                    time.sleep(2) # Jeda anti-spam
                    continue
                    
                current_price_idr = float(df.iloc[-1]['close'])
                
                # ==== DYNAMIC STRATEGY ROUTING ====
                strategy_name = state.strategy or "MA Crossover"
                if strategy_name == "RSI Breakout":
                    strategy = RSIBreakoutStrategy()
                elif strategy_name == "Bollinger Bands":
                    strategy = BollingerBandsStrategy()
                else:
                    strategy = MovingAverageStrategy(fast_period=10, slow_period=50)
                    
                signal = strategy.analyze(df)
                
                # ==== RISK MANAGEMENT (TP/SL) ====
                # Sinkronisasi Total Investasi (Berguna jika pengguna mengisi Manual Entry Price di UI)
                if (state.entry_price or 0.0) > 0 and (state.total_idr_invested or 0.0) == 0.0:
                    balances = indodax_executor.get_balance()
                    asset_bal_sync = balances.get(koin_utama, 0)
                    if asset_bal_sync > 0:
                        state.total_idr_invested = asset_bal_sync * state.entry_price
                        logging.info(f"[{symbol_indodax}] Sinkronisasi modal awal DCA: Rp {state.total_idr_invested:,.0f}")
                        
                entry_price = state.entry_price or 0.0
                if entry_price > 0:
                    # Trailing Stop: Update highest price
                    highest_price = state.highest_price_since_buy or 0.0
                    if current_price_idr > highest_price:
                        state.highest_price_since_buy = current_price_idr
                        highest_price = current_price_idr
                        
                    pnl_pct = ((current_price_idr - entry_price) / entry_price) * 100
                    
                    # 1. Cek Dynamic ROI
                    dynamic_target_pct = coin_tp_pct
                    if state.use_dynamic_roi and state.dynamic_roi_config and state.last_buy_time:
                        try:
                            roi_rules = json.loads(state.dynamic_roi_config)
                            minutes_held = (time.time() - state.last_buy_time) / 60.0
                            
                            # Cari target dari rule yang menitnya sudah terlampaui
                            for min_str in sorted(roi_rules.keys(), key=int, reverse=True):
                                if minutes_held >= int(min_str):
                                    dynamic_target_pct = float(roi_rules[min_str])
                                    break
                                    
                            if pnl_pct >= dynamic_target_pct:
                                logging.info(f"[{symbol_indodax}] DYNAMIC ROI TERCAPAI! Waktu tahan: {minutes_held:.0f}mnt. Target: {dynamic_target_pct}%. PnL: {pnl_pct:.2f}%")
                                signal = "SELL"
                        except Exception as e:
                            logging.error(f"[{symbol_indodax}] Gagal memproses Dynamic ROI: {e}")
                    
                    # 1.5 Cek DCA / Safety Orders
                    if signal != "SELL" and state.use_dca:
                        dca_count = state.dca_completed_orders or 0
                        max_orders = state.dca_max_orders or 3
                        if dca_count < max_orders:
                            step_pct = state.dca_step_pct or 3.0
                            drop_threshold = step_pct * (dca_count + 1)
                            
                            if pnl_pct <= -drop_threshold:
                                volume_scale = state.dca_volume_scale or 1.0
                                dca_amount = coin_buy_amount * (volume_scale ** dca_count)
                                
                                balances_dca = indodax_executor.get_balance()
                                idr_bal_dca = balances_dca.get('IDR', 0)
                                
                                if idr_bal_dca >= dca_amount or DRY_RUN:
                                    logging.info(f"[{symbol_indodax}] 🚨 Harga turun {-pnl_pct:.2f}%. Memicu DCA #{dca_count+1} sebesar Rp {dca_amount:,.0f}!")
                                    order = indodax_executor.place_buy_order(symbol_indodax, dca_amount)
                                    if order:
                                        msg = f"🛒 **DCA / SAFETY ORDER!**\nTarget: {symbol_indodax}\nTahap: #{dca_count+1}/{max_orders}\nNominal: Rp {dca_amount:,.0f}\nHarga Beli: Rp {current_price_idr:,.0f}"
                                        notifier.send_message(msg)
                                        
                                        state.total_idr_invested = (state.total_idr_invested or 0.0) + dca_amount
                                        state.dca_completed_orders = dca_count + 1
                                        
                                        # Kalkulasi Average Price Akurat
                                        time.sleep(2) # Tunggu Indodax settle balance
                                        new_balances = indodax_executor.get_balance()
                                        new_asset_bal = new_balances.get(koin_utama, 0)
                                        if new_asset_bal > 0:
                                            new_avg_price = state.total_idr_invested / new_asset_bal
                                            logging.info(f"[{symbol_indodax}] Average Price turun dari Rp {entry_price:,.0f} menjadi Rp {new_avg_price:,.0f}")
                                            state.entry_price = new_avg_price
                                            state.highest_price_since_buy = new_avg_price
                                            
                                        # Catat ke history
                                        db_session.add(TradeHistory(symbol=symbol_indodax, action=f"BUY (DCA {dca_count+1})", price=current_price_idr, nominal=f"Rp {dca_amount:,.0f}"))
                                        db_session.commit()
                                else:
                                    logging.warning(f"[{symbol_indodax}] DCA #{dca_count+1} gagal! Saldo IDR tidak cukup (Butuh: {dca_amount:,.0f}, Tersedia: {idr_bal_dca:,.0f})")
                    
                    # 2. Cek Trailing Stop Loss (jika aktif)
                    if signal != "SELL" and state.use_trailing_stop:
                        if highest_price > 0:
                            drop_pct = ((highest_price - current_price_idr) / highest_price) * 100
                            if drop_pct >= (state.trailing_stop_pct or 2.0):
                                logging.info(f"[{symbol_indodax}] TRAILING STOP TERKENA! Turun {drop_pct:.2f}% dari puncak. PnL: {pnl_pct:.2f}%")
                                signal = "SELL"
                    
                    # 3. Cek Fixed TP/SL (Fallback)
                    if signal != "SELL":
                        if pnl_pct <= -coin_sl_pct:
                            logging.warning(f"[{symbol_indodax}] STOP LOSS TERKENA! Rugi: {pnl_pct:.2f}% (Batas: -{coin_sl_pct}%)")
                            signal = "SELL"
                        # Hanya cek Fixed TP jika Dynamic ROI tidak aktif (karena Dynamic ROI menimpa target)
                        elif not state.use_dynamic_roi and pnl_pct >= coin_tp_pct:
                            logging.info(f"[{symbol_indodax}] TAKE PROFIT TERCAPAI! Untung: {pnl_pct:.2f}% (Target: +{coin_tp_pct}%)")
                            signal = "SELL"
                
                # ==== COOLDOWN LOGIC ====
                current_time = time.time()
                if signal == "BUY" and (current_time - last_sell_times[symbol_indodax]) < (COOLDOWN_HOURS * 3600):
                    logging.info(f"[{symbol_indodax}] Sinyal BUY diabaikan (Dalam masa Cooldown {COOLDOWN_HOURS} jam).")
                    signal = "HOLD"

                logging.info(f"[{symbol_indodax}] Harga: Rp {current_price_idr:,.0f} | Sinyal Akhir: {signal}")
                
                # Eksekusi Logika jika ada sinyal Beli/Jual
                balances = indodax_executor.get_balance()
                idr_bal = balances.get('IDR', 0)
                asset_bal = balances.get(koin_utama, 0)
                
                # Sinkronisasi Cerdas: Jika koin sudah tidak ada di Indodax (dijual manual), reset harga beli
                # BUGFIX: Cek ke API Indodax apakah masih ada antrean beli (pending order). Jika ada, JANGAN hapus ingatan.
                # BUGFIX: Turunkan batas dari 11000 ke 5000, karena pembelian minimum 10.000 (setelah dipotong fee) akan menjadi ~9.970.
                estimated_value_idr = asset_bal * current_price_idr
                
                if estimated_value_idr < 5000 and (state.entry_price or 0.0) > 0:
                    if not indodax_executor.has_open_orders(symbol_indodax):
                        logging.info(f"[{symbol_indodax}] Saldo koin kosong & tidak ada pending order, menghapus Harga Beli dari memori.")
                        state.entry_price = 0.0
                        state.highest_price_since_buy = 0.0
                        state.last_buy_time = 0.0
                        state.total_idr_invested = 0.0
                        state.dca_completed_orders = 0

                if signal == "BUY" and last_signals[symbol_indodax] != "BUY":
                    if idr_bal >= coin_buy_amount or DRY_RUN:
                        order = indodax_executor.place_buy_order(symbol_indodax, coin_buy_amount)
                        
                        if order: # Validasi Ganda: Order benar-benar sukses di Indodax
                            msg = f"🟢 **SINYAL BELI!**\nTarget: {symbol_indodax}\nNominal: Rp {coin_buy_amount:,.0f}"
                            notifier.send_message(msg)
                            last_signals[symbol_indodax] = "BUY"
                            state.entry_price = current_price_idr
                            state.highest_price_since_buy = current_price_idr
                            state.last_buy_time = time.time()
                            state.total_idr_invested = coin_buy_amount
                            state.dca_completed_orders = 0
                            
                            # Catat ke Tabel TradeHistory (Tercatat abadi di Database)
                            trade = TradeHistory(
                                symbol=symbol_indodax, action="BUY", price=current_price_idr, nominal=f"Rp {coin_buy_amount:,.0f}"
                            )
                            db_session.add(trade)
                        else:
                            logging.error(f"[{symbol_indodax}] API Indodax menolak Beli. Mencoba lagi putaran berikutnya.")
                            # KITA TIDAK mengupdate last_signals, agar bot mengulang coba beli di menit depan
                    else:
                        logging.warning(f"[{symbol_indodax}] Saldo IDR tidak cukup.")
                        last_signals[symbol_indodax] = "BUY" # Saldo habis, bungkam agar tidak spam Indodax
                        
                elif signal == "SELL" and last_signals[symbol_indodax] != "SELL":
                    # Filter Receh: Batas aman Rp 11.000 (Standar Emas)
                    if estimated_value_idr >= 11000 or DRY_RUN:
                        amount_to_sell = 0.001 if DRY_RUN else asset_bal 
                        order = indodax_executor.place_sell_order(symbol_indodax, amount_to_sell)
                        
                        if order: # Validasi Ganda: Order benar-benar sukses di Indodax
                            # HITUNG PnL
                            current_entry = state.entry_price or 0.0
                            realized_pnl = None
                            if current_entry > 0:
                                realized_pnl = ((current_price_idr - current_entry) / current_entry) * 100
                                
                            msg = f"🔴 **SINYAL JUAL!**\nTarget: {symbol_indodax}\nKoin Dijual: {amount_to_sell} {koin_utama}"
                            notifier.send_message(msg)
                            last_signals[symbol_indodax] = "SELL"
                            state.entry_price = 0.0
                            state.highest_price_since_buy = 0.0
                            state.last_buy_time = 0.0
                            state.total_idr_invested = 0.0
                            state.dca_completed_orders = 0
                            last_sell_times[symbol_indodax] = time.time()
                            
                            # Catat ke Tabel TradeHistory
                            trade = TradeHistory(
                                symbol=symbol_indodax, action="SELL", price=current_price_idr, nominal=f"{amount_to_sell} {koin_utama}", pnl_pct=realized_pnl
                            )
                            db_session.add(trade)
                        else:
                            logging.error(f"[{symbol_indodax}] API Indodax menolak Jual. Koin aman, mencoba lagi nanti.")
                            # KITA TIDAK mengupdate last_signals, agar bot ngotot jual lagi di menit depan (Smart Retry)
                    else:
                        logging.warning(f"[{symbol_indodax}] Sisa saldo receh (Di bawah Rp 11.000). Penjualan diabaikan.")
                        last_signals[symbol_indodax] = "SELL" # Saldo receh, bungkam agar tidak spam error Indodax
                
                # Panggil MIXA AI setiap 15 menit per koin
                current_time = time.time()
                mixa_insight = ""
                if current_time - last_mixa_times[symbol_indodax] >= 900:
                    logging.info(f"[{symbol_indodax}] Meminta analisis dari MIXA AI...")
                    rsi_val = float(df.iloc[-1]['RSI_14']) if 'RSI_14' in df.columns else 50.0
                    
                    config = db_session.query(AppConfig).filter_by(key="GEMINI_MODEL").first()
                    model_name = config.value if config else "gemini-2.5-flash"
                    
                    mixa_insight = mixa.get_market_insight(current_price_idr, signal, rsi_val, model_name=model_name)
                    last_mixa_times[symbol_indodax] = current_time
                    
                # Siapkan data grafik untuk disimpan ke Database (Format JSON)
                df_history = df.tail(50).copy()
                df_history = df_history.assign(timestamp=df_history['timestamp'].astype(str))
                chart_data_json = df_history.to_json(orient='records')
                
                # Simpan update State ke Tabel BotState (Objek state sudah diambil di awal loop)
                state.current_price = current_price_idr
                state.signal = signal
                state.mode = status_mode
                state.balances = json.dumps(indodax_executor.get_balance())
                
                # Timpa insight jika MIXA baru saja dipanggil
                if mixa_insight:
                     state.mixa_insight = mixa_insight
                # Jika belum pernah diisi
                elif not state.mixa_insight:
                     state.mixa_insight = "Menunggu inisialisasi MIXA AI..."
                     
                state.chart_data = chart_data_json
                
                # Commit langsung agar Web Svelte/Streamlit bisa membacanya secara Real-time
                db_session.commit()
                
                # Istirahat 3 Detik antar koin agar Cloudflare tidak mencurigai pergerakan robotik
                time.sleep(3)
                
            db_session.close()
            
            # 5. Istirahat 1 Menit (Stealth) setelah 1 putaran penuh semua koin selesai
            wait_seconds = 60
            logging.info(f"Satu putaran sukses. Menunggu {wait_seconds} detik untuk menyamarkan jejak...\n")
            time.sleep(wait_seconds)
            
        except Exception as e:
            logging.error(f"Terjadi kesalahan pada loop utama: {e}")
            notifier.send_message(f"⚠️ **Error pada Bot Multi-Koin**\n{e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
