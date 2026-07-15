#!/bin/bash
# Jalankan skrip migrasi SaaS (tambahkan kolom/update skema) sebelum backend menyala
python migrate_saas.py

# Menjalankan Bot Engine di latar belakang
python main.py &

# Menjalankan FastAPI Server di latar depan (foreground)
uvicorn api:app --host 0.0.0.0 --port 8000
