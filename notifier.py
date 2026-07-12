import requests
import logging
from database import get_db, AppConfig
import os

class TelegramNotifier:
    """Mengurus pengiriman pesan notifikasi ke Chat Telegram Anda."""
    def __init__(self, token: str = None, chat_id: str = None):
        # Fallback awal dari .env jika ada
        self._env_token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._env_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        
    def _get_credentials(self):
        """Ambil kredensial dari AppConfig (Database), fallback ke .env"""
        db = next(get_db())
        try:
            token_conf = db.query(AppConfig).filter_by(key="TELEGRAM_TOKEN").first()
            chat_conf = db.query(AppConfig).filter_by(key="TELEGRAM_CHAT_ID").first()
            
            token = token_conf.value if token_conf and token_conf.value else self._env_token
            chat_id = chat_conf.value if chat_conf and chat_conf.value else self._env_chat_id
            return token, chat_id
        except Exception as e:
            logging.error(f"Error baca AppConfig Telegram: {e}")
            return self._env_token, self._env_chat_id
        finally:
            db.close()

    def send_message(self, message: str):
        token, chat_id = self._get_credentials()
        
        if not token or not chat_id:
            logging.info("Lewati Telegram: Token atau Chat ID belum dikonfigurasi (DB atau .env kosong).")
            return
            
        base_url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            response = requests.post(base_url, json=payload)
            if not response.ok:
                logging.error(f"Gagal mengirim pesan Telegram: {response.text}")
        except Exception as e:
            logging.error(f"Error koneksi Telegram: {e}")
