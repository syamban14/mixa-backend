import os
from dotenv import load_dotenv
from exchange_handler import IndodaxHandler
load_dotenv()
api_key = os.getenv("INDODAX_API_KEY")
secret_key = os.getenv("INDODAX_SECRET_KEY")
executor = IndodaxHandler(api_key=api_key, secret_key=secret_key)
print("Testing privatePostOpenOrders...")
try:
    orders = executor.exchange.privatePostOpenOrders({'pair': 'ondo_idr'})
    print("Result ONDO/IDR:", orders)
    all_orders = executor.exchange.privatePostOpenOrders()
    print("Result ALL:", all_orders)
except Exception as e:
    print("Error:", e)
