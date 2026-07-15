import logging
from database import BotState
from exchange_handler import IndodaxHandler

def run_auto_screener(indodax_executor: IndodaxHandler, db, max_active_coins: int = 5):
    """
    Menjalankan AI Autopilot Screener:
    1. Prune: Menghapus koin yang tidak aktif (saldo 0, tidak ada open orders, performa buruk).
    2. Add: Menambahkan koin baru yang sedang trending di Indodax.
    """
    logging.info("[SCREENER] Memulai proses Auto-Screener...")
    try:
        # 1. PRUNE (Bersihkan Koin Tidak Aktif)
        active_states = db.query(BotState).filter_by(is_active=1).all()
        for state in active_states:
            symbol = state.symbol
            koin_utama = symbol.split('/')[0]
            
            # Cek saldo
            balances = indodax_executor.get_balance()
            asset_bal = balances.get(koin_utama, 0)
            current_price = indodax_executor.get_current_price(symbol)
            estimated_value = asset_bal * current_price
            
            # Jika saldo kurang dari batas minimum (Rp 10.000) dan tidak ada open orders
            if estimated_value < 10000:
                if not indodax_executor.has_open_orders(symbol):
                    logging.info(f"[SCREENER] Menonaktifkan {symbol} karena saldo kosong dan tidak ada transaksi aktif.")
                    state.is_active = 0
                    db.commit()

        # Update jumlah koin aktif setelah prune
        active_states = db.query(BotState).filter_by(is_active=1).all()
        active_count = len(active_states)
        
        if active_count >= max_active_coins:
            logging.info(f"[SCREENER] Koin aktif ({active_count}) sudah mencapai batas maksimal ({max_active_coins}). Screener selesai.")
            return

        # 2. ADD (Cari Koin Trending Baru)
        slots_available = max_active_coins - active_count
        logging.info(f"[SCREENER] Mencari maksimal {slots_available} koin baru yang potensial...")
        
        try:
            tickers = indodax_executor.exchange.fetch_tickers()
        except Exception as e:
            logging.error(f"[SCREENER] Gagal mengambil tickers: {e}")
            return
            
        # Kumpulkan semua pasangan koin IDR
        idr_markets = []
        for sym, data in tickers.items():
            if sym.endswith('/IDR'):
                # Pastikan data volume dan change tidak None
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
        
        # Sortir top 20 tersebut berdasarkan kenaikan (Trending/Momentum)
        top_volume.sort(key=lambda x: x['change'], reverse=True)
        
        added_count = 0
        active_symbols = [s.symbol for s in active_states]
        
        for market in top_volume:
            sym = market['symbol']
            change = market['change']
            
            # Hindari FOMO ekstrim (misal naik > 20% dalam sehari rawan koreksi)
            # Dan cari yang naik positif
            if sym not in active_symbols and 0 < change < 20:
                logging.info(f"[SCREENER] Menambahkan koin potensial: {sym} (Vol: {market['volume']:,.0f}, Naik: {change}%)")
                
                # Cek apakah koin ini pernah ada di database sebelumnya (inactive)
                existing = db.query(BotState).filter_by(symbol=sym).first()
                if existing:
                    existing.is_active = 1
                    existing.signal = "HOLD"
                    existing.entry_price = 0.0
                else:
                    new_state = BotState(
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
                    
        logging.info(f"[SCREENER] Screener selesai. Menambahkan {added_count} koin baru.")
        
    except Exception as e:
        logging.error(f"[SCREENER] Error: {e}")
