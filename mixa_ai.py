import os
import time
import requests
import logging

class MixaAI:
    def __init__(self):
        # Mengambil API Key dari .env yang sudah diamankan
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
        
    def get_market_insight(self, price: float, ma_signal: str, rsi: float, model_name: str = "gemini-2.5-flash") -> str:
        """Mengirim data teknikal ke Google Gemini dan mengembalikan opini analisis dengan auto-retry."""
        if not self.api_key:
            return "Kunci API Gemini tidak ditemukan di .env."
            
        url = f"{self.base_url.format(model_name)}?key={self.api_key}"
        
        # Perintah (Prompt) untuk Gemini 2.5 Flash
        prompt = f"""
Anda adalah MIXA AI, sebuah kecerdasan buatan elit spesialis algoritmik trading kripto.
Tugas Anda adalah membaca data teknikal berikut dan memberikan opini ringkas kepada pemilik Anda.

DATA TEKNIKAL SAAT INI:
- Harga: Rp {price:,.0f}
- Sinyal Moving Average (Tren): {ma_signal}
- Level RSI (14): {rsi:.2f} (Ingat: <30 = Oversold, >70 = Overbought)

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
