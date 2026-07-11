from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
import datetime
import os

Base = declarative_base()

def get_wib_time():
    """Mengembalikan waktu saat ini dalam zona waktu WIB (UTC+7)"""
    return datetime.datetime.utcnow() + datetime.timedelta(hours=7)

# Tabel Status Terkini Bot (Diperbarui Setiap Siklus)
class BotState(Base):
    __tablename__ = 'bot_state'
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
    total_idr_invested = Column(Float, default=0.0)
    mixa_insight = Column(String)
    chart_data = Column(String) # Disimpan dalam format JSON string (50 Lilin Terakhir)
    last_update = Column(DateTime, default=get_wib_time, onupdate=get_wib_time)

# Tabel Konfigurasi Aplikasi (Key-Value)
class AppConfig(Base):
    __tablename__ = 'app_config'
    key = Column(String, primary_key=True)
    value = Column(String)

# Tabel Riwayat Transaksi (Bertambah Terus Tanpa Batas)
class TradeHistory(Base):
    __tablename__ = 'trade_history'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True)
    action = Column(String) # BUY atau SELL
    price = Column(Float)
    nominal = Column(String)
    pnl_pct = Column(Float, nullable=True) # Persentase profit/rugi jika action == SELL
    timestamp = Column(DateTime, default=get_wib_time)

def init_db(db_url="sqlite:///data/trading.db"):
    """Inisialisasi koneksi Database. Bisa baca dari .env jika kelak pindah ke PostgreSQL."""
    os.makedirs("data", exist_ok=True)
    url = os.getenv("DATABASE_URL", db_url)
    # Jika menggunakan sqlite, tambahkan parameter khusus agar aman untuk multi-thread
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    
    engine = create_engine(url, connect_args=connect_args, echo=False)
    Base.metadata.create_all(engine)
    
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
                conn.commit()
            except Exception:
                pass
                
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal
