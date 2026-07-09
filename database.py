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
                print(f"Migrasi TP dilewati: {e}")
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN stop_loss_pct FLOAT DEFAULT 5.0"))
            except Exception as e:
                print(f"Migrasi SL dilewati: {e}")
            try:
                conn.execute(text("ALTER TABLE bot_state ADD COLUMN strategy VARCHAR DEFAULT 'MA Crossover'"))
            except Exception as e:
                print(f"Migrasi Strategy dilewati: {e}")
            try:
                conn.commit()
            except Exception:
                pass
                
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal
