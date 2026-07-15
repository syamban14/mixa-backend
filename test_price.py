import os
from exchange_handler import IndodaxHandler
from dotenv import load_dotenv
load_dotenv()
api_key = os.getenv("INDODAX_API_KEY")
secret_key = os.getenv("INDODAX_SECRET_KEY")
executor = IndodaxHandler(api_key=api_key, secret_key=secret_key)
print("ONDO/IDR Price:", executor.get_current_price('ONDO/IDR'))
