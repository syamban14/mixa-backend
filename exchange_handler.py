import ccxt
import pandas as pd
import logging
import requests
import time

class BinanceHandler:
    def __init__(self):
        # Kita tidak butuh API Key untuk membaca data grafik publik dari Binance
        self.exchange = ccxt.binance({'enableRateLimit': True})
        logging.info("BinanceHandler initialized (Fungsi: Sensor Mata / Pengambil Grafik)")

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """Mengambil data candlestick historis dari Binance"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = df.assign(timestamp=pd.to_datetime(df['timestamp'], unit='ms'))
            return df
        except Exception as e:
            logging.error(f"Error mengambil data grafik dari Binance untuk {symbol}: {e}")
            return pd.DataFrame()


class IndodaxHandler:
    def __init__(self, api_key: str, secret_key: str, dry_run: bool = True):
        self.exchange = ccxt.indodax({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True,
        })
        self.dry_run = dry_run
        logging.info(f"IndodaxHandler initialized (Fungsi: Tangan Eksekutor - Dry Run: {dry_run})")

    def fetch_hidden_ohlcv(self, symbol: str = "BTCIDR", tf: str = "15", limit: int = 50) -> pd.DataFrame:
        """Menarik data candlestick dari API rahasia Indodax dengan stealth mode (User-Agent)."""
        try:
            # Hitung timestamp UNIX
            to_ts = int(time.time())
            # tf=15 berarti 1 candle = 15 menit. Total detik = 15 * 60 * limit.
            from_ts = to_ts - (int(tf) * 60 * limit)
            
            url = f"https://indodax.com/tradingview/history_v2?symbol={symbol}&tf={tf}&from={from_ts}&to={to_ts}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": f"https://indodax.com/trade/{symbol}"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                return pd.DataFrame()
                
            df = pd.DataFrame(data)
            # Standarisasi kolom mengikuti format Binance
            df = df.rename(columns={
                'Time': 'timestamp', 
                'Open': 'open', 
                'High': 'high', 
                'Low': 'low', 
                'Close': 'close', 
                'Volume': 'volume'
            })
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
                
            df = df.assign(timestamp=pd.to_datetime(df['timestamp'], unit='s') + pd.Timedelta(hours=7))
            return df
        except Exception as e:
            logging.error(f"Gagal menarik grafik dari API Rahasia Indodax: {e}")
            return pd.DataFrame()
    def get_balance(self) -> dict:
        """Mengambil informasi saldo nyata Rupiah dan Kripto di akun Indodax."""
        try:
            # Selalu coba tarik saldo asli meskipun dalam mode Dry Run
            balance = self.exchange.fetch_balance()
            return balance.get('free', {})
        except Exception as e:
            logging.error(f"Error mengambil saldo akun Indodax: {e}")
            if self.dry_run:
                logging.info("Menggunakan saldo simulasi (Rp 1.000.000) karena akses API gagal.")
                return {"IDR": 1000000.0, "BTC": 0.0} 
            return {}
            
    def get_current_price(self, symbol: str) -> float:
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            logging.error(f"Error mengambil harga terkini Indodax untuk {symbol}: {e}")
            return 0.0

    def place_buy_order(self, symbol: str, amount_idr: float) -> dict:
        """Mengeksekusi order Beli dengan pseudo-Market (Limit Order +1% slippage) di Indodax."""
        if self.dry_run:
            logging.info(f"[DRY RUN] Eksekusi Beli di Indodax {symbol} senilai Rp {amount_idr}")
            return {"status": "dry_run", "side": "buy"}
            
        try:
            current_price = self.get_current_price(symbol)
            if current_price <= 0:
                return {}
            amount_base = amount_idr / current_price
            
            # API Indodax tidak mendukung Market Order murni. 
            # Kita gunakan Limit Order dengan harga beli +1% agar langsung Match (Pseudo-Market)
            buy_price = current_price * 1.01 
            
            # API v2 fix: sertakan quote_quantity di params
            params = {
                "quote_quantity": amount_idr,
                "base_quantity": amount_base
            }
            order = self.exchange.create_limit_buy_order(symbol, amount_base, buy_price, params=params)
            logging.info(f"BUY Order Indodax BERHASIL: {order}")
            return order
        except Exception as e:
            logging.error(f"Order Beli Indodax GAGAL: {e}")
            return {}

    def place_sell_order(self, symbol: str, amount_base: float) -> dict:
        """Mengeksekusi order Jual dengan pseudo-Market (Limit Order -1% slippage) di Indodax."""
        if self.dry_run:
            logging.info(f"[DRY RUN] Eksekusi Jual di Indodax {amount_base} koin {symbol}")
            return {"status": "dry_run", "side": "sell"}
            
        try:
            current_price = self.get_current_price(symbol)
            # Limit Order dengan harga jual -1% agar langsung Match (Pseudo-Market)
            sell_price = current_price * 0.99
            
            # API v2 fix: sertakan quote_quantity di params
            quote_qty = amount_base * sell_price
            params = {
                "quote_quantity": quote_qty,
                "base_quantity": amount_base
            }
            order = self.exchange.create_limit_sell_order(symbol, amount_base, sell_price, params=params)
            logging.info(f"SELL Order Indodax BERHASIL: {order}")
            return order
        except Exception as e:
            logging.error(f"Order Jual Indodax GAGAL: {e}")
            return {}
