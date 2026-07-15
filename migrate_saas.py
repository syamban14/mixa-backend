import os
import logging
from sqlalchemy import text
from database import init_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_migration():
    logging.info("Memulai migrasi skema database untuk SaaS (Multi-Tenant)...")
    
    # Ambil sesi database (bisa Postgres atau SQLite lokal)
    SessionLocal = init_db()
    
    # Gunakan engine langsung untuk menjalankan DDL (Data Definition Language)
    engine = SessionLocal.kw['bind']
    
    with engine.connect() as conn:
        try:
            # 1. Tambahkan kolom user_id dengan default email admin sementara
            admin_email = "admin@mixa.ai"
            logging.info(f"Menambahkan kolom user_id (Default: {admin_email})...")
            
            # Kita menggunakan try-except berantai agar skrip tetap berjalan jika kolom sudah ada
            try:
                conn.execute(text(f"ALTER TABLE bot_state ADD COLUMN user_id VARCHAR DEFAULT '{admin_email}'"))
            except Exception as e:
                logging.warning(f"bot_state.user_id mungkin sudah ada: {e}")
                
            try:
                conn.execute(text(f"ALTER TABLE app_config ADD COLUMN user_id VARCHAR DEFAULT '{admin_email}'"))
            except Exception as e:
                logging.warning(f"app_config.user_id mungkin sudah ada: {e}")
                
            try:
                conn.execute(text(f"ALTER TABLE trade_history ADD COLUMN user_id VARCHAR DEFAULT '{admin_email}'"))
            except Exception as e:
                pass
                
            try:
                conn.execute(text(f"ALTER TABLE notifications ADD COLUMN user_id VARCHAR DEFAULT '{admin_email}'"))
            except Exception as e:
                pass
            
            # 2. Ubah Primary Key bot_state menjadi (user_id, symbol)
            # Karena SQLite tidak mendukung DROP CONSTRAINT atau ADD PRIMARY KEY dengan mudah, 
            # query ini dikhususkan jika menggunakan PostgreSQL.
            if engine.url.drivername.startswith("postgres"):
                logging.info("Mengatur ulang Primary Key pada bot_state dan app_config (PostgreSQL)...")
                try:
                    # Drop existing PK (biasanya bernama bot_state_pkey)
                    conn.execute(text("ALTER TABLE bot_state DROP CONSTRAINT IF EXISTS bot_state_pkey CASCADE"))
                    conn.execute(text("ALTER TABLE bot_state ADD PRIMARY KEY (user_id, symbol)"))
                except Exception as e:
                    logging.error(f"Gagal mengubah PK bot_state: {e}")
                    
                try:
                    conn.execute(text("ALTER TABLE app_config DROP CONSTRAINT IF EXISTS app_config_pkey CASCADE"))
                    conn.execute(text("ALTER TABLE app_config ADD PRIMARY KEY (user_id, key)"))
                except Exception as e:
                    logging.error(f"Gagal mengubah PK app_config: {e}")
                    
            conn.commit()
            logging.info("✅ Migrasi skema database berhasil diselesaikan!")
            
        except Exception as e:
            logging.error(f"Terjadi kesalahan fatal saat migrasi: {e}")
            conn.rollback()

if __name__ == "__main__":
    run_migration()
