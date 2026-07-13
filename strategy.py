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

class RSIBreakoutStrategy(BaseStrategy):
    """
    Strategi Teknikal menggunakan Relative Strength Index (RSI).
    Beli: Jika RSI menyilang ke atas batas oversold (misal 30).
    Jual: Jika RSI menyilang ke bawah batas overbought (misal 70).
    """
    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def analyze(self, df: pd.DataFrame) -> str:
        if df.empty or len(df) < self.period + 1:
            return "HOLD"
            
        df = df.copy()
        
        # Kalkulasi RSI murni
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        df = df.assign(RSI=rsi)
        
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        # Sinyal BUY: oversold breakout (dari bawah 30 naik ke atas 30)
        if prev_row['RSI'] <= self.oversold and last_row['RSI'] > self.oversold:
            return "BUY"
            
        # Sinyal SELL: overbought breakout (dari atas 70 turun ke bawah 70)
        elif prev_row['RSI'] >= self.overbought and last_row['RSI'] < self.overbought:
            return "SELL"
            
        return "HOLD"

class BollingerBandsStrategy(BaseStrategy):
    """
    Strategi Teknikal menggunakan Bollinger Bands.
    Beli: Jika harga penutupan menyentuh/menyilang ke atas pita bawah (Lower Band).
    Jual: Jika harga penutupan menyentuh/menyilang ke bawah pita atas (Upper Band).
    """
    def __init__(self, period: int = 20, std_dev: float = 2.0):
        self.period = period
        self.std_dev = std_dev

    def analyze(self, df: pd.DataFrame) -> str:
        if df.empty or len(df) < self.period:
            return "HOLD"
            
        df = df.copy()
        
        # Kalkulasi SMA dan Standard Deviation
        sma = df['close'].rolling(window=self.period).mean()
        std = df['close'].rolling(window=self.period).std()
        
        upper_band = sma + (std * self.std_dev)
        lower_band = sma - (std * self.std_dev)
        
        df = df.assign(UpperBand=upper_band, LowerBand=lower_band)
        
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        # Sinyal BUY: Harga close menembus dari bawah ke atas Lower Band
        if prev_row['close'] <= prev_row['LowerBand'] and last_row['close'] > last_row['LowerBand']:
            return "BUY"
            
        # Sinyal SELL: Harga close menembus dari atas ke bawah Upper Band
        elif prev_row['close'] >= prev_row['UpperBand'] and last_row['close'] < last_row['UpperBand']:
            return "SELL"
            
        return "HOLD"

class GridTradingStrategy(BaseStrategy):
    """
    Strategi Grid Trading (Ping-Pong).
    Membeli saat harga berada di area Support (titik terendah N-candle terakhir).
    Menjual saat harga berada di area Resistance (titik tertinggi N-candle terakhir).
    Sangat cocok untuk pasar sideways.
    """
    def __init__(self, period: int = 20):
        self.period = period

    def analyze(self, df: pd.DataFrame) -> str:
        if df.empty or len(df) < self.period:
            return "HOLD"
            
        df = df.copy()
        
        highest_high = df['high'].rolling(window=self.period).max()
        lowest_low = df['low'].rolling(window=self.period).min()
        
        df = df.assign(HighestHigh=highest_high, LowestLow=lowest_low)
        
        last_row = df.iloc[-1]
        
        # Beli jika harga mendekati Lowest Low (Toleransi 0.5%)
        if last_row['close'] <= last_row['LowestLow'] * 1.005:
            return "BUY"
            
        # Jual jika harga mendekati Highest High (Toleransi 0.5%)
        elif last_row['close'] >= last_row['HighestHigh'] * 0.995:
            return "SELL"
            
        return "HOLD"
