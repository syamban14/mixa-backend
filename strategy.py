import pandas as pd

class BaseStrategy:
    """Kelas dasar (Blueprint) agar strategi bisa ditukar-tukar dengan mudah."""
    def analyze(self, df: pd.DataFrame) -> str:
        """Mengembalikan nilai 'BUY', 'SELL', atau 'HOLD'"""
        raise NotImplementedError("Fungsi ini harus diimplementasikan di subclass")

class MovingAverageStrategy(BaseStrategy):
    """
    Strategi Teknikal menggunakan Simple Moving Average (SMA).
    Beli: Jika SMA periode cepat menyilang ke atas SMA periode lambat (Golden Cross).
    Jual: Jika SMA periode cepat menyilang ke bawah SMA periode lambat (Death Cross).
    """
    def __init__(self, fast_period: int = 10, slow_period: int = 50):
        self.fast_period = fast_period
        self.slow_period = slow_period

    def analyze(self, df: pd.DataFrame) -> str:
        if df.empty or len(df) < self.slow_period:
            return "HOLD"
            
        # Salin dataframe untuk menghindari pandas FutureWarning (ChainedAssignmentError)
        df = df.copy()
        
        # Kalkulasi RSI (14 Periode) secara manual murni menggunakan pandas
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi_14 = 100 - (100 / (1 + rs))
        
        # Kalkulasi dua garis Moving Average menggunakan metode assign yang 100% aman
        df = df.assign(**{
            f'SMA_{self.fast_period}': df['close'].rolling(window=self.fast_period).mean(),
            f'SMA_{self.slow_period}': df['close'].rolling(window=self.slow_period).mean(),
            'RSI_14': rsi_14
        })
        
        # Ambil 2 candle terakhir untuk melihat apakah ada persilangan
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        # Kondisi BELI (BUY)
        if prev_row[f'SMA_{self.fast_period}'] <= prev_row[f'SMA_{self.slow_period}'] and \
           last_row[f'SMA_{self.fast_period}'] > last_row[f'SMA_{self.slow_period}']:
            return "BUY"
            
        # Kondisi JUAL (SELL)
        elif prev_row[f'SMA_{self.fast_period}'] >= prev_row[f'SMA_{self.slow_period}'] and \
             last_row[f'SMA_{self.fast_period}'] < last_row[f'SMA_{self.slow_period}']:
            return "SELL"
            
        return "HOLD"

class HybridAIStrategy(BaseStrategy):
    """
    Strategi Pembungkus (Wrapper) untuk integrasi AI (Hermes AI Agent) di masa depan.
    """
    def __init__(self, ta_strategy: BaseStrategy):
        self.ta_strategy = ta_strategy
        
    def analyze(self, df: pd.DataFrame) -> str:
        # Langkah 1: Dapatkan sinyal teknikal (misal dari Moving Average)
        ta_signal = self.ta_strategy.analyze(df)
        
        # Langkah 2 (Masa Depan): 
        # Jika Hermes AI Agent Anda mendeteksi sentimen buruk di Telegram/Berita,
        # kita bisa membatalkan sinyal BUY dari teknikal.
        # Contoh:
        # ai_sentiment = fetch_ai_sentiment()
        # if ta_signal == "BUY" and ai_sentiment == "NEGATIVE": return "HOLD"
        
        # Untuk saat ini, teruskan sinyal teknikal secara murni
        return ta_signal
