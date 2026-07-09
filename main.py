import os
import time
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

from exchange_handler import IndodaxHandler
from strategy import MovingAverageStrategy
from notifier import TelegramNotifier
from mixa_ai import MixaAI
from database import init_db, BotState, TradeHistory, AppConfig

# Konfigurasi Catatan (Logging) agar tercetak di layar
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    # 1. Muat pengaturan rahasia dari file .env
    load_dotenv()
    
    API_KEY = os.getenv('INDODAX_API_KEY')
    SECRET_KEY = os.getenv('INDODAX_SECRET_KEY')
    
    # Pair Indodax bisa banyak, dipisahkan koma. Contoh: BTC/IDR,ETH/IDR
    trading_pairs_env = os.getenv('TRADING_PAIRS', 'BTC/IDR,ETH/IDR')
    TARGET_COINS = [p.strip() for p in trading_pairs_env.split(',')]
    
    BUY_AMOUNT_IDR = float(os.getenv('BUY_AMOUNT_IDR', 50000))
    DRY_RUN = os.getenv('DRY_RUN', 'True').lower() in ('true', '1', 't')
    
    # Konfigurasi Risk Management
    STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', 5.0))
    TAKE_PROFIT_PCT = float(os.getenv('TAKE_PROFIT_PCT', 10.0))
    COOLDOWN_HOURS = float(os.getenv('COOLDOWN_HOURS', 2.0))
    
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

    # 2. Inisialisasi Modul & Database
    indodax_executor = IndodaxHandler(api_key=API_KEY, secret_key=SECRET_KEY, dry_run=DRY_RUN)
    notifier = TelegramNotifier(token=TELEGRAM_TOKEN, chat_id=TELEGRAM_CHAT_ID)
    mixa = MixaAI()
    
    # Inisialisasi Database (SQLite Engine)
    Session = init_db()
    
    # Inisialisasi Strategi (Moving Average)
    strategy = MovingAverageStrategy(fast_period=10, slow_period=50)
    
    status_mode = 'SIMULASI (DRY RUN)' if DRY_RUN else 'RIIL (UANG ASLI)'
    logging.info(f"Bot Multi-Koin dimulai. Mode: {status_mode}")
    logging.info(f"Target Pantauan: {', '.join(TARGET_COINS)}")
    
    notifier.send_message(f"🚀 **Bot Multi-Koin Aktif**\nTarget: {', '.join(TARGET_COINS)}\nMode: {status_mode}\nDatabase: SQLite Aktif")

    # === MEMORI SEMENTARA (RAM) ===
    # Karena ada banyak koin, kita simpan status masing-masing koin di Dictionary memori
    # untuk mengecek apakah sinyal berubah (mencegah spam Beli/Jual)
    last_signals = {coin: "HOLD" for coin in TARGET_COINS}
    # Staggering: Koin 1 langsung panggil AI, Koin 2 tunggu 3 menit, Koin 3 tunggu 6 menit, dst.
    # Waktu sekarang dikurangi 900 detik (15 mnt) agar koin pertama langsung eksekusi,
    # ditambah jeda 180 detik (3 mnt) per koin berikutnya.
    current_t = time.time()
    last_mixa_times = {coin: current_t - 900 + (i * 180) for i, coin in enumerate(TARGET_COINS)}

    entry_prices = {coin: 0.0 for coin in TARGET_COINS}
    last_sell_times = {coin: 0.0 for coin in TARGET_COINS}

    
    # 3. Looping Utama Bot
    while True:
        try:
            db_session = Session()
            
            # Putaran untuk setiap koin
            for symbol_indodax in TARGET_COINS:
                koin_utama = symbol_indodax.split('/')[0] # 'BTC'
                api_symbol = symbol_indodax.replace('/', '') # 'BTCIDR'
                
                logging.info(f"[{symbol_indodax}] Mengambil grafik dari API Rahasia Indodax...")
                df = indodax_executor.fetch_hidden_ohlcv(api_symbol, tf="15", limit=200)
                
                if df.empty:
                    logging.warning(f"[{symbol_indodax}] Gagal menarik grafik. Lanjut ke koin berikutnya.")
                    time.sleep(2) # Jeda anti-spam
                    continue
                    
                current_price_idr = float(df.iloc[-1]['close'])
                signal = strategy.analyze(df)
                
                # ==== RISK MANAGEMENT (TP/SL) ====
                entry_price = entry_prices[symbol_indodax]
                if entry_price > 0:
                    pnl_pct = ((current_price_idr - entry_price) / entry_price) * 100
                    if pnl_pct <= -STOP_LOSS_PCT:
                        logging.warning(f"[{symbol_indodax}] STOP LOSS TERKENA! Rugi: {pnl_pct:.2f}%")
                        signal = "SELL"
                    elif pnl_pct >= TAKE_PROFIT_PCT:
                        logging.info(f"[{symbol_indodax}] TAKE PROFIT TERCAPAI! Untung: {pnl_pct:.2f}%")
                        signal = "SELL"
                
                # ==== COOLDOWN LOGIC ====
                current_time = time.time()
                if signal == "BUY" and (current_time - last_sell_times[symbol_indodax]) < (COOLDOWN_HOURS * 3600):
                    logging.info(f"[{symbol_indodax}] Sinyal BUY diabaikan (Dalam masa Cooldown {COOLDOWN_HOURS} jam).")
                    signal = "HOLD"

                logging.info(f"[{symbol_indodax}] Harga: Rp {current_price_idr:,.0f} | Sinyal Akhir: {signal}")
                
                # Eksekusi Logika jika ada sinyal Beli/Jual
                if signal == "BUY" and last_signals[symbol_indodax] != "BUY":
                    balances = indodax_executor.get_balance()
                    idr_bal = balances.get('IDR', 0)
                    
                    if idr_bal >= BUY_AMOUNT_IDR or DRY_RUN:
                        order = indodax_executor.place_buy_order(symbol_indodax, BUY_AMOUNT_IDR)
                        
                        if order: # Validasi Ganda: Order benar-benar sukses di Indodax
                            msg = f"🟢 **SINYAL BELI!**\nTarget: {symbol_indodax}\nNominal: Rp {BUY_AMOUNT_IDR:,}"
                            notifier.send_message(msg)
                            last_signals[symbol_indodax] = "BUY"
                            entry_prices[symbol_indodax] = current_price_idr
                            
                            # Catat ke Tabel TradeHistory (Tercatat abadi di Database)
                            trade = TradeHistory(
                                symbol=symbol_indodax, action="BUY", price=current_price_idr, nominal=f"Rp {BUY_AMOUNT_IDR:,}"
                            )
                            db_session.add(trade)
                        else:
                            logging.error(f"[{symbol_indodax}] API Indodax menolak Beli. Mencoba lagi putaran berikutnya.")
                            # KITA TIDAK mengupdate last_signals, agar bot mengulang coba beli di menit depan
                    else:
                        logging.warning(f"[{symbol_indodax}] Saldo IDR tidak cukup.")
                        last_signals[symbol_indodax] = "BUY" # Saldo habis, bungkam agar tidak spam Indodax
                        
                elif signal == "SELL" and last_signals[symbol_indodax] != "SELL":
                    balances = indodax_executor.get_balance()
                    asset_bal = balances.get(koin_utama, 0)
                    estimated_value_idr = asset_bal * current_price_idr
                    
                    # Filter Receh: Batas aman Rp 11.000 (Standar Emas)
                    if estimated_value_idr >= 11000 or DRY_RUN:
                        amount_to_sell = 0.001 if DRY_RUN else asset_bal 
                        order = indodax_executor.place_sell_order(symbol_indodax, amount_to_sell)
                        
                        if order: # Validasi Ganda: Order benar-benar sukses di Indodax
                            msg = f"🔴 **SINYAL JUAL!**\nTarget: {symbol_indodax}\nKoin Dijual: {amount_to_sell} {koin_utama}"
                            notifier.send_message(msg)
                            last_signals[symbol_indodax] = "SELL"
                            entry_prices[symbol_indodax] = 0.0
                            last_sell_times[symbol_indodax] = time.time()
                            
                            # Catat ke Tabel TradeHistory
                            trade = TradeHistory(
                                symbol=symbol_indodax, action="SELL", price=current_price_idr, nominal=f"{amount_to_sell} {koin_utama}"
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
                
                # Simpan State ke Tabel BotState
                state = db_session.query(BotState).filter_by(symbol=symbol_indodax).first()
                if not state:
                    state = BotState(symbol=symbol_indodax)
                    db_session.add(state)
                    
                state.current_price = current_price_idr
                state.signal = signal
                state.mode = status_mode
                state.balances = json.dumps(indodax_executor.get_balance())
                state.entry_price = entry_prices[symbol_indodax]
                
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
