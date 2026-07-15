import os
from dotenv import load_dotenv
from exchange_handler import IndodaxHandler
load_dotenv()
api_key = os.getenv("INDODAX_API_KEY")
secret_key = os.getenv("INDODAX_SECRET_KEY")
executor = IndodaxHandler(api_key=api_key, secret_key=secret_key)
print("Testing fetch_open_orders('ONDO/IDR')...")
try:
    orders = executor.exchange.fetch_open_orders('ONDO/IDR')
    print("Result length:", len(orders))
    print("Result:", orders)
except Exception as e:
    print("Error:", e)
