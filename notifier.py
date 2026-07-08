import requests
import logging

class TelegramNotifier:
    """Mengurus pengiriman pesan notifikasi ke Chat Telegram Anda."""
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        
    def send_message(self, message: str):
        if not self.token or not self.chat_id:
            logging.info("Lewati Telegram: Token atau Chat ID tidak diisi di .env")
            return
            
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            response = requests.post(self.base_url, json=payload)
            if not response.ok:
                logging.error(f"Gagal mengirim pesan Telegram: {response.text}")
        except Exception as e:
            logging.error(f"Error koneksi Telegram: {e}")
