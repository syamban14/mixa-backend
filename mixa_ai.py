import os
import time
import requests
import logging

class MixaAI:
    def __init__(self):
        # Mengambil API Key dari .env yang sudah diamankan
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
        
    def get_market_insight(self, price: float, ma_signal: str, rsi: float, model_name: str = "gemini-2.5-flash", news: list = None) -> str:
        """Mengirim data teknikal & berita ke Google Gemini dan mengembalikan opini analisis dengan auto-retry."""
        if not self.api_key:
            return "Kunci API Gemini tidak ditemukan di .env."
            
        url = f"{self.base_url.format(model_name)}?key={self.api_key}"
        
        news_str = "- " + "\n- ".join(news) if news else "Tidak ada berita penting."
        
        # Perintah (Prompt) untuk Gemini 2.5 Flash
        prompt = f"""
Anda adalah MIXA AI, sebuah kecerdasan buatan elit spesialis algoritmik trading kripto.
Tugas Anda adalah membaca data teknikal berikut dan memberikan opini ringkas kepada pemilik Anda.

DATA TEKNIKAL SAAT INI:
- Harga: Rp {price:,.0f}
- Sinyal Moving Average (Tren): {ma_signal}
- Level RSI (14): {rsi:.2f} (Ingat: <30 = Oversold, >70 = Overbought)

BERITA TERKINI (JIKA ADA):
{news_str}

TUGAS:
Berikan analisis pasar yang tajam, futuristik, dan sangat ringkas (maksimal 2 kalimat pendek). 
Berikan pandangan apakah trader harus waspada, optimis, atau menahan diri.
Dilarang keras memberikan disclaimer keamanan atau sapaan basa-basi.
"""
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=15)
                response.raise_for_status()
                data = response.json()
                if 'candidates' in data and len(data['candidates']) > 0:
                    insight = data['candidates'][0]['content']['parts'][0]['text'].strip()
                    return insight.replace('**', '')
                else:
                    return "MIXA AI sedang memproses anomali pasar..."
            except requests.exceptions.HTTPError as e:
                # Jika error 503 atau 429, lakukan retry
                if response.status_code in [503, 429, 500, 502, 504]:
                    logging.warning(f"Server Google sibuk (Error {response.status_code}). Percobaan ulang ke-{attempt+1}/{max_retries} dalam 5 detik...")
                    time.sleep(5)
                else:
                    logging.error(f"Error komunikasi MIXA AI: {e}")
                    return "Sinyal koneksi ke satelit MIXA AI terputus."
            except Exception as e:
                logging.error(f"Error komunikasi MIXA AI: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    return "Sinyal koneksi ke satelit MIXA AI terputus."
                    
        return "MIXA AI gagal menghubungi server Google setelah 3 kali percobaan."

    def get_ai_trading_signal(self, df, current_pos: bool, model_name: str = "gemini-2.5-flash", news: list = None) -> dict:
        """Mengevaluasi kondisi pasar dan mengembalikan keputusan BUY/SELL/HOLD dalam format JSON."""
        if not self.api_key:
            return {"signal": "HOLD", "reason": "Kunci API Gemini tidak ditemukan."}
            
        import json
        url = f"{self.base_url.format(model_name)}?key={self.api_key}"
        
        news_str = "- " + "\n- ".join(news) if news else "Tidak ada berita penting."
        
        # Ekstrak 10 candle terakhir
        recent_data = df.tail(10)[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        chart_str = recent_data.to_string(index=False)
        
        # Ekstrak indikator terkini
        last_row = df.iloc[-1]
        price = float(last_row['close'])
        rsi = float(last_row.get('RSI_14', 50))
        
        pos_status = "Punya aset (Bisa JUAL atau HOLD)." if current_pos else "Tidak punya aset (Bisa BELI atau HOLD)."
        
        prompt = f"""
Anda adalah AI Algoritma Trading Kripto Kuantitatif.
Tugas Anda adalah membaca data teknikal dan menentukan keputusan trading: BUY, SELL, atau HOLD.

DATA HARGA TERAKHIR (10 Candle):
{chart_str}

INDIKATOR SAAT INI:
- Harga: Rp {price:,.0f}
- RSI (14): {rsi:.2f} (Oversold < 30, Overbought > 70)

STATUS POSISI TRADER:
{pos_status}

BERITA TERKINI:
{news_str}

INSTRUKSI WAJIB:
- Jika RSI oversold dan harga mulai mantul naik (bullish candlestick), pilih BUY.
- Jika RSI overbought dan tren mulai turun (bearish candlestick), pilih SELL.
- Jika bingung, tren tidak jelas, sideway kasar, atau tidak ada momentum, WAJIB pilih HOLD.
- Jika status posisi "Tidak punya aset", Anda TIDAK BOLEH memilih SELL.
- Jika status posisi "Punya aset", Anda TIDAK BOLEH memilih BUY.
- Balas HANYA dengan format JSON murni tanpa markdown block.
Contoh:
{{"signal": "BUY", "reason": "RSI sudah oversold (25) dan terjadi pembalikan harga (bullish engulfing) didukung berita positif."}}
"""
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=20)
                response.raise_for_status()
                data = response.json()
                if 'candidates' in data and len(data['candidates']) > 0:
                    result_str = data['candidates'][0]['content']['parts'][0]['text'].strip()
                    # Bersihkan json markdown block jika LLM bandel
                    result_str = result_str.replace("```json", "").replace("```", "").strip()
                    try:
                        result_json = json.loads(result_str)
                        # Validasi output
                        sig = result_json.get('signal', 'HOLD').upper()
                        if sig not in ['BUY', 'SELL', 'HOLD']:
                            sig = 'HOLD'
                        result_json['signal'] = sig
                        return result_json
                    except:
                        return {"signal": "HOLD", "reason": f"Gagal memparsing JSON dari AI. Output: {result_str}"}
                else:
                    return {"signal": "HOLD", "reason": "AI tidak mengembalikan analisis yang valid."}
            except requests.exceptions.HTTPError as e:
                if response.status_code in [503, 429, 500, 502, 504]:
                    logging.warning(f"Server Google sibuk ({response.status_code}). Retry ke-{attempt+1}/{max_retries}...")
                    time.sleep(5)
                else:
                    logging.error(f"Error AI Signal: {e}")
                    return {"signal": "HOLD", "reason": "Sistem API LLM terputus."}
            except Exception as e:
                logging.error(f"Error AI Signal: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    return {"signal": "HOLD", "reason": "Koneksi satelit AI terganggu."}
                    
        return {"signal": "HOLD", "reason": "AI gagal merespons setelah 3 kali percobaan."}
