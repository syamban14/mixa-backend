import logging
from database import BotState
from exchange_handler import IndodaxHandler

def fetch_trending_tickers(indodax_executor: IndodaxHandler) -> list:
    """Mengambil top 20 koin IDR yang sedang trending secara global."""
    try:
        tickers = indodax_executor.exchange.fetch_tickers()
    except Exception as e:
        logging.error(f"[SCREENER GLOBAL] Gagal mengambil tickers dari Indodax: {e}")
        return []
        
    idr_markets = []
    for sym, data in tickers.items():
        if sym.endswith('/IDR'):
            vol = data.get('quoteVolume', 0)
            change = data.get('percentage', 0)
            if vol is not None and change is not None:
                idr_markets.append({
                    'symbol': sym,
                    'volume': vol,
                    'change': change
                })
                
    # Sortir berdasarkan Volume IDR terbesar, lalu ambil top 20
    idr_markets.sort(key=lambda x: x['volume'], reverse=True)
    top_volume = idr_markets[:20]
    
    # Sortir top 20 berdasarkan kenaikan (Trending/Momentum)
    top_volume.sort(key=lambda x: x['change'], reverse=True)
    return top_volume

def run_auto_screener_for_user(user_id: str, indodax_executor: IndodaxHandler, db, top_volume: list, max_active_coins: int = 5):
    """
    Menjalankan AI Autopilot Screener untuk satu pengguna:
    1. Prune: Menghapus koin yang tidak aktif (saldo 0, tidak ada open orders).
    2. Add: Menambahkan koin baru dari daftar top_volume.
    """
    logging.info(f"[{user_id}] [SCREENER] Mengevaluasi portofolio koin...")
    try:
        # 1. PRUNE (Bersihkan Koin Tidak Aktif)
        active_states = db.query(BotState).filter_by(user_id=user_id, is_active=1).all()
        for state in active_states:
            symbol = state.symbol
            koin_utama = symbol.split('/')[0]
            
            balances = indodax_executor.get_balance()
            asset_bal = balances.get(koin_utama, 0)
            current_price = indodax_executor.get_current_price(symbol)
            estimated_value = asset_bal * current_price
            
            if estimated_value < 10000:
                if not indodax_executor.has_open_orders(symbol):
                    logging.info(f"[{user_id}] [SCREENER] Menonaktifkan {symbol} karena saldo kosong & tidak ada transaksi.")
                    state.is_active = 0
                    db.commit()

        # Hitung koin aktif setelah prune
        active_states = db.query(BotState).filter_by(user_id=user_id, is_active=1).all()
        active_count = len(active_states)
        
        if active_count >= max_active_coins:
            logging.info(f"[{user_id}] [SCREENER] Kuota koin penuh ({active_count}/{max_active_coins}).")
            return

        # 2. ADD (Tambahkan koin dari top_volume)
        slots_available = max_active_coins - active_count
        added_count = 0
        active_symbols = [s.symbol for s in active_states]
        
        for market in top_volume:
            sym = market['symbol']
            change = market['change']
            
            # Hindari FOMO ekstrim (>20%) dan cari tren positif (>0%)
            if sym not in active_symbols and 0 < change < 20:
                logging.info(f"[{user_id}] [SCREENER] Menambahkan koin potensial: {sym} (+{change}%)")
                
                existing = db.query(BotState).filter_by(user_id=user_id, symbol=sym).first()
                if existing:
                    existing.is_active = 1
                    existing.signal = "HOLD"
                    existing.entry_price = 0.0
                else:
                    new_state = BotState(
                        user_id=user_id,
                        symbol=sym, 
                        is_active=1, 
                        signal="HOLD", 
                        mode="AUTO",
                        strategy="MA Crossover",
                        buy_amount=20000.0,
                        take_profit_pct=10.0,
                        stop_loss_pct=5.0
                    )
                    db.add(new_state)
                
                db.commit()
                added_count += 1
                
                if added_count >= slots_available:
                    break
                    
    except Exception as e:
        logging.error(f"[{user_id}] [SCREENER] Error: {e}")
