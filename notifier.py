import requests
import logging
from database import init_db, AppConfig
import os

class TelegramNotifier:
    """Mengurus pengiriman pesan notifikasi ke Chat Telegram terpusat (Multi-Tenant)."""
    def __init__(self, token: str = None, chat_id: str = None):
        # Fallback awal dari .env jika ada
        self._env_token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._env_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.Session = init_db()
        
    def _get_credentials(self, user_id: str):
        """Ambil kredensial. Token diambil dari admin atau .env, chat_id spesifik dari user"""
        db = self.Session()
        try:
            # Ambil token utama dari admin atau env
            admin_token_conf = db.query(AppConfig).filter_by(user_id="admin@mixa.ai", key="TELEGRAM_BOT_TOKEN").first()
            master_token = admin_token_conf.value if admin_token_conf and admin_token_conf.value else self._env_token
            
            # Ambil chat id dari user spesifik
            user_chat_conf = db.query(AppConfig).filter_by(user_id=user_id, key="TELEGRAM_CHAT_ID").first()
            user_chat_id = user_chat_conf.value if user_chat_conf and user_chat_conf.value else None
            
            # Khusus untuk admin, jika tidak ketemu di db bisa fallback ke env
            if user_id == "admin@mixa.ai" and not user_chat_id:
                user_chat_id = self._env_chat_id
                
            return master_token, user_chat_id
        except Exception as e:
            logging.error(f"Error baca AppConfig Telegram: {e}")
            return self._env_token, self._env_chat_id if user_id == "admin@mixa.ai" else None
        finally:
            db.close()

    def send_message(self, user_id: str, message: str):
        if not user_id:
            return
            
        token, chat_id = self._get_credentials(user_id)
        
        if not token or not chat_id:
            return
            
        base_url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            response = requests.post(base_url, json=payload, timeout=5)
            if not response.ok:
                logging.error(f"Gagal mengirim pesan Telegram ke {user_id}: {response.text}")
        except Exception as e:
            logging.error(f"Error koneksi Telegram ke {user_id}: {e}")
