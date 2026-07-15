from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
import datetime
import os

Base = declarative_base()

def get_wib_time():
    """Mengembalikan waktu saat ini dalam zona waktu WIB (UTC+7)"""
    return datetime.datetime.utcnow() + datetime.timedelta(hours=7)

# Tabel User (SaaS)
class User(Base):
    __tablename__ = 'users'
    email = Column(String, primary_key=True) # Gunakan Email sebagai Primary Key untuk kemudahan integrasi Google
    name = Column(String)
    picture = Column(String)
    created_at = Column(DateTime, default=get_wib_time)
    trial_ends_at = Column(DateTime)
    subscription_ends_at = Column(DateTime)
    is_active = Column(Integer, default=1)

# Tabel Status Terkini Bot (Diperbarui Setiap Siklus)
class BotState(Base):
    __tablename__ = 'bot_state'
    user_id = Column(String, primary_key=True, default='admin@mixa.ai')
    symbol = Column(String, primary_key=True)
    current_price = Column(Float)
    signal = Column(String)
    mode = Column(String)
    balances = Column(String) # Disimpan dalam format JSON string
    entry_price = Column(Float)
    take_profit_pct = Column(Float, default=10.0)
    stop_loss_pct = Column(Float, default=5.0)
    strategy = Column(String, default='MA Crossover')
    buy_amount = Column(Float, default=20000.0)
    is_active = Column(Integer, default=1) # SQLite doesn't have native BOOLEAN, use Integer 1/0
    use_trailing_stop = Column(Integer, default=0) # 0 = False, 1 = True
    trailing_stop_pct = Column(Float, default=2.0)
    highest_price_since_buy = Column(Float, default=0.0)
    use_dynamic_roi = Column(Integer, default=0) # 0 = False, 1 = True
    dynamic_roi_config = Column(String, default='{"0": 5.0, "60": 2.0, "1440": 0.5}')
    last_buy_time = Column(Float, default=0.0)
    use_dca = Column(Integer, default=0) # 0 = False, 1 = True
    dca_max_orders = Column(Integer, default=3)
    dca_step_pct = Column(Float, default=3.0)
    dca_volume_scale = Column(Float, default=1.0)
    dca_completed_orders = Column(Integer, default=0)
    use_macro_trend = Column(Integer, default=0) # 0 = False, 1 = True
    use_trailing_buy = Column(Integer, default=0)
    trailing_buy_pct = Column(Float, default=1.0)
    trailing_buy_active = Column(Integer, default=0)
    trailing_buy_lowest_price = Column(Float, default=0.0)
    use_whale_radar = Column(Integer, default=0) # 0 = False, 1 = True
    use_autotune = Column(Integer, default=0) # 0 = Manual, 1 = Autopilot
    last_autotune_time = Column(Float, default=0.0) # Timestamp terakhir kali autotune berjalan
    total_idr_invested = Column(Float, default=0.0)
    mixa_insight = Column(String)
    chart_data = Column(String) # Disimpan dalam format JSON string (50 Lilin Terakhir)
    last_update = Column(DateTime, default=get_wib_time, onupdate=get_wib_time)

# Tabel Konfigurasi Aplikasi (Key-Value)
class AppConfig(Base):
    __tablename__ = 'app_config'
    user_id = Column(String, primary_key=True, default='admin@mixa.ai')
    key = Column(String, primary_key=True)
    value = Column(String)

# Tabel Riwayat Transaksi (Bertambah Terus Tanpa Batas)
class Notification(Base):
    __tablename__ = 'notifications'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String, index=True, default='admin@mixa.ai')
    message = Column(String, nullable=False)
    type = Column(String, default='info') # info, warning, success, error
    timestamp = Column(DateTime, default=get_wib_time)
    is_read = Column(Integer, default=0) # 0 = unread, 1 = read

class TradeHistory(Base):
    __tablename__ = 'trade_history'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True, default='admin@mixa.ai')
    symbol = Column(String, index=True)
    action = Column(String) # BUY atau SELL
    price = Column(Float)
    nominal = Column(String)
    pnl_pct = Column(Float, nullable=True) # Persentase profit/rugi jika action == SELL
    timestamp = Column(DateTime, default=get_wib_time)

def init_db(db_url="sqlite:///data/trading.db"):
    """Inisialisasi koneksi Database. Bisa baca dari .env jika kelak pindah ke PostgreSQL."""
    os.makedirs("data", exist_ok=True)
    
    # 1. AUTO BACKUP SQLITE SEBELUM NGAPA-NGAPAIN
    sqlite_path = "data/trading.db"
    backup_path = "data/trading.db.bak"
    if os.path.exists(sqlite_path) and not os.path.exists(backup_path):
        import shutil
        import logging
        try:
            shutil.copy2(sqlite_path, backup_path)
            logging.info(f"Berhasil membuat backup database lokal ke {backup_path}")
        except Exception as e:
            logging.error(f"Gagal membackup database: {e}")

    url = os.getenv("DATABASE_URL", db_url)
    is_postgres = url.startswith("postgres")
    
    # Jika menggunakan sqlite, tambahkan parameter khusus agar aman untuk multi-thread
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    
    engine = create_engine(url, connect_args=connect_args, echo=False)
    
    import time
    import logging
    max_retries = 10
    for attempt in range(max_retries):
        try:
            Base.metadata.create_all(engine)
            break
        except Exception as e:
            if attempt < max_retries - 1:
                logging.warning(f"Menunggu database siap (percobaan {attempt+1}/{max_retries})...")
                time.sleep(3)
            else:
                logging.error("Gagal terhubung ke database setelah beberapa kali percobaan.")
                raise e
    
    # Auto-Migration untuk SQLite (Jika update versi)
    if url.startswith("sqlite"):
        from sqlalchemy import text
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN take_profit_pct FLOAT DEFAULT 10.0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN stop_loss_pct FLOAT DEFAULT 5.0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN strategy VARCHAR DEFAULT 'MA Crossover'"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN buy_amount FLOAT DEFAULT 20000.0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN is_active INTEGER DEFAULT 1"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE trade_history ADD COLUMN pnl_pct FLOAT NULL"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN use_trailing_stop INTEGER DEFAULT 0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN trailing_stop_pct FLOAT DEFAULT 2.0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN highest_price_since_buy FLOAT DEFAULT 0.0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN use_dynamic_roi INTEGER DEFAULT 0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN dynamic_roi_config VARCHAR DEFAULT '{\"0\": 5.0, \"60\": 2.0, \"1440\": 0.5}'"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN last_buy_time FLOAT DEFAULT 0.0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN use_dca INTEGER DEFAULT 0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN dca_max_orders INTEGER DEFAULT 3"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN dca_step_pct FLOAT DEFAULT 3.0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN dca_volume_scale FLOAT DEFAULT 1.0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN dca_completed_orders INTEGER DEFAULT 0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN total_idr_invested FLOAT DEFAULT 0.0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN use_macro_trend INTEGER DEFAULT 0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN use_trailing_buy INTEGER DEFAULT 0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN trailing_buy_pct FLOAT DEFAULT 1.0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN trailing_buy_active INTEGER DEFAULT 0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN trailing_buy_lowest_price FLOAT DEFAULT 0.0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN use_whale_radar INTEGER DEFAULT 0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN use_autotune INTEGER DEFAULT 0"))
            except Exception as e:
                pass
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN last_autotune_time FLOAT DEFAULT 0.0"))
            except Exception as e:
                pass
            try:
                conn.commit()
            except Exception:
                pass
                
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # 2. SEAMLESS CROSS-DATABASE MIGRATION (SQLite -> PostgreSQL)
    if is_postgres:
        import logging
        pg_session = SessionLocal()
        # Cek apakah PostgreSQL kosong (belum ada config/bot)
        if pg_session.query(AppConfig).count() == 0 and pg_session.query(BotState).count() == 0:
            if os.path.exists(sqlite_path):
                logging.info("Memulai migrasi otomatis dari SQLite ke PostgreSQL...")
                try:
                    sqlite_engine = create_engine(f"sqlite:///{sqlite_path}")
                    SqliteSessionLocal = sessionmaker(bind=sqlite_engine)
                    sqlite_session = SqliteSessionLocal()
                    
                    # Migrasi AppConfig
                    for row in sqlite_session.query(AppConfig).all():
                        pg_session.add(AppConfig(key=row.key, value=row.value))
                    
                    # Migrasi BotState
                    for row in sqlite_session.query(BotState).all():
                        state_dict = row.__dict__.copy()
                        state_dict.pop('_sa_instance_state', None)
                        pg_session.add(BotState(**state_dict))
                        
                    # Migrasi TradeHistory
                    for row in sqlite_session.query(TradeHistory).all():
                        hist_dict = row.__dict__.copy()
                        hist_dict.pop('_sa_instance_state', None)
                        hist_dict.pop('id', None) # Biarkan postgres auto increment
                        pg_session.add(TradeHistory(**hist_dict))
                        
                    # Migrasi Notification
                    for row in sqlite_session.query(Notification).all():
                        notif_dict = row.__dict__.copy()
                        notif_dict.pop('_sa_instance_state', None)
                        notif_dict.pop('id', None)
                        pg_session.add(Notification(**notif_dict))
                        
                    pg_session.commit()
                    logging.info("Migrasi data ke PostgreSQL berhasil 100%!")
                except Exception as e:
                    logging.error(f"Gagal melakukan migrasi ke PostgreSQL: {e}")
                    pg_session.rollback()
                finally:
                    sqlite_session.close()
        pg_session.close()

    return SessionLocal
