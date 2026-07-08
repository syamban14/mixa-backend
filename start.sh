#!/bin/bash
# Menjalankan Bot Engine di latar belakang
python main.py &

# Menjalankan FastAPI Server di latar depan (foreground)
uvicorn api:app --host 0.0.0.0 --port 8000
