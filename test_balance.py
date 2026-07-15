import os
from dotenv import load_dotenv
from exchange_handler import IndodaxHandler
load_dotenv()
api_key = os.getenv("INDODAX_API_KEY")
secret_key = os.getenv("INDODAX_SECRET_KEY")
executor = IndodaxHandler(api_key=api_key, secret_key=secret_key)
print("Testing get_balance()...")
try:
    balances = executor.get_balance()
    print("ONDO Balance:", balances.get('ONDO', 0))
    print("All nonzero balances:", {k: v for k,v in balances.items() if v > 0})
except Exception as e:
    print("Error:", e)
