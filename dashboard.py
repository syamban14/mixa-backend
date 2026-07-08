import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import time
import os

from database import init_db, BotState, TradeHistory

# Pengaturan dasar halaman web (Harus dipanggil paling pertama)
st.set_page_config(
    page_title="Indodax Bot Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Judul Web
st.title("🤖 Indodax Trading Bot Dashboard")
st.markdown("Memantau kinerja bot 100% Indodax Native (Multi-Koin & Database Ready).")

try:
    Session = init_db()
    db_session = Session()
    
    # Ambil semua koin yang sedang dipantau oleh bot dari Database
    all_states = db_session.query(BotState).all()
    
    if not all_states:
        st.warning("Database kosong. Menunggu bot (`main.py`) dijalankan untuk memompa data...")
    else:
        # Buat daftar nama koin (Contoh: ["BTC/IDR", "ETH/IDR"])
        coin_names = [state.symbol for state in all_states]
        
        # Streamlit Tabs (Satu Tab untuk satu Koin)
        tabs = st.tabs(coin_names)
        
        for i, tab in enumerate(tabs):
            with tab:
                state = all_states[i]
                
                # Blok Analisis MIXA AI
                insight = state.mixa_insight or "Menunggu inisialisasi MIXA AI..."
                st.info(f"**🧠 Analisis MIXA AI ({state.symbol}):** {insight}")
                    
                # Baris Pertama: Kartu Metrik Utama
                col1, col2, col3, col4, col5 = st.columns(5)
                
                with col1:
                    st.metric("Mode Operasi", state.mode)
                with col2:
                    st.metric("Pair Trading", state.symbol)
                with col3:
                    st.metric("Harga Terkini (IDR)", f"Rp {state.current_price:,.0f}")
                with col4:
                    signal = state.signal or "HOLD"
                    signal_color = "🟢 BUY" if signal == "BUY" else "🔴 SELL" if signal == "SELL" else "⚪ HOLD"
                    st.metric("Sinyal Terakhir", signal_color)
                with col5:
                    entry_price = state.entry_price or 0.0
                    if entry_price > 0:
                        pnl_pct = ((state.current_price - entry_price) / entry_price) * 100
                        pnl_color = "🟢" if pnl_pct >= 0 else "🔴"
                        st.metric("P&L Sementara", f"{pnl_color} {pnl_pct:,.2f}%", delta=f"{pnl_pct:,.2f}%")
                    else:
                        st.metric("P&L Sementara", "⚪ Standby (No Coin)")
                    
                st.divider()
                
                # Baris Kedua: Saldo dan Grafik
                col_chart, col_bal = st.columns([3, 1])
                
                with col_bal:
                    st.subheader("💳 Saldo Indodax")
                    if state.balances:
                        balances = json.loads(state.balances)
                        for koin, jumlah in balances.items():
                            if jumlah > 0:
                                st.write(f"**{koin}:** {jumlah:,.4f}")
                            
                    st.caption(f"Pembaruan Terakhir: {state.last_update}")
                    st.info("💡 Jangan tutup Terminal yang menjalankan `main.py` agar data ini terus diperbarui.")
                    
                with col_chart:
                    st.subheader("📊 Grafik Pergerakan (50 Lilin Terakhir)")
                    if state.chart_data:
                        chart_data = json.loads(state.chart_data)
                        df = pd.DataFrame(chart_data)
                        
                        # Buat grafik bertingkat
                        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                                            vertical_spacing=0.03, 
                                            row_width=[0.2, 0.2, 0.6])
                        
                        fig.add_trace(go.Candlestick(x=df['timestamp'],
                                        open=df['open'], high=df['high'],
                                        low=df['low'], close=df['close'],
                                        name='Harga'), row=1, col=1)
                        
                        if 'SMA_10' in df.columns and 'SMA_50' in df.columns:
                            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['SMA_10'], line=dict(color='cyan', width=1), name='MA Cepat (10)'), row=1, col=1)
                            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['SMA_50'], line=dict(color='yellow', width=1), name='MA Lambat (50)'), row=1, col=1)
                        
                        colors = ['green' if close >= open else 'red' for open, close in zip(df['open'], df['close'])]
                        fig.add_trace(go.Bar(x=df['timestamp'], y=df['volume'], marker_color=colors, name='Volume'), row=2, col=1)
                        
                        if 'RSI_14' in df.columns:
                            fig.add_trace(go.Scatter(x=df['timestamp'], y=df['RSI_14'], line=dict(color='magenta', width=2), name='RSI (14)'), row=3, col=1)
                            fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1, opacity=0.5)
                            fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1, opacity=0.5)
                        
                        fig.update_layout(
                            xaxis_rangeslider_visible=False,
                            xaxis2_rangeslider_visible=False,
                            xaxis3_rangeslider_visible=False,
                            margin=dict(l=0, r=0, t=0, b=0),
                            template="plotly_dark", 
                            height=700, 
                            showlegend=False
                        )
                        st.plotly_chart(fig, width='stretch', key=f"chart_{state.symbol}")
                    else:
                        st.info("Menunggu data grafik dari bot utama...")
                        
                st.divider()
                st.subheader("📝 Riwayat Transaksi (Trade History)")
                
                # Tarik riwayat transaksi dari Database khusus untuk koin ini
                history_records = db_session.query(TradeHistory).filter_by(symbol=state.symbol).order_by(TradeHistory.timestamp.desc()).all()
                if history_records:
                    hist_data = [{
                        "Waktu": h.timestamp,
                        "Aksi": h.action,
                        "Harga (IDR)": f"Rp {h.price:,.0f}",
                        "Nominal": h.nominal
                    } for h in history_records]
                    df_hist = pd.DataFrame(hist_data)
                    st.dataframe(df_hist, use_container_width=True, hide_index=True)
                else:
                    st.info("Belum ada transaksi Beli/Jual untuk koin ini.")
                    
    db_session.close()

except Exception as e:
    st.error(f"Terjadi kesalahan saat memuat Dashboard: {e}")

# Web akan diam selama 3 detik, lalu merefresh halamannya sendiri secara natural
time.sleep(3)
st.rerun()
