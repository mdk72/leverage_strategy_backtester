import streamlit as st
import pandas as pd
from datetime import datetime
from utils import load_config, save_config, load_steps_data, save_steps_data

def render():
    st.header("⚙️ 전략 설정 (Configuration)")
    
    # Load Config
    if 'config' not in st.session_state:
        st.session_state.config = load_config()
    
    config = st.session_state.config
    
    # --- Layout: 2 Columns ---
    col1, col2 = st.columns([1, 1], gap="large")
    
    with col1:
        st.subheader("1. 기본 설정")
        
        # Capital Helper (Manwon)
        current_cap = config.get("initial_capital", 10000)
        # Check if it looks like USD or KRW. Logic: If < 1000000 likely USD, else KRW? 
        # User prompt showed 1억 (100,000,000), but code default is 10000 ($).
        # Let's Stick to the existing logic but add a helper or just keep it as is.
        # User requested "Match Split UI" which has Manwon input.
        # However, the strategy seems to default to TQQQ/UPRO (USD). I will keep it as "Initial Capital ($)" for now to avoid logic break, 
        # but organize it better.
        
        new_base = st.text_input("Base Ticker", value=config.get("base_ticker", "QQQ"))
        new_adds = st.text_input("Add Tickers (comma sep)", value=config.get("add_tickers", "TQQQ"))
        
        new_cap = st.number_input("Initial Capital ($)", value=int(config.get("initial_capital", 10000)), step=1000)
        
        st.subheader("2. 백테스트 기간")
        min_date = datetime(1990, 1, 1)
        max_date = datetime.today()
        default_start = datetime.strptime(str(config.get("start_date", "2025-01-01")).split()[0], "%Y-%m-%d")
        default_end = datetime.strptime(str(config.get("end_date", datetime.today().strftime("%Y-%m-%d"))).split()[0], "%Y-%m-%d")
        
        new_start = st.date_input("Start Date", default_start, min_value=min_date, max_value=max_date)
        new_end = st.date_input("End Date", default_end, min_value=min_date, max_value=max_date)
        
    with col2:
        st.subheader("3. 매매/리스크 설정")
        
        # Sell Mode
        curr_mode = config.get("sell_mode", "limit")
        mode_idx = 0 if curr_mode == "limit" else 1
        
        sell_mode_label = st.radio(
            "익절 기준 가격 (Profit Taking):",
            ("Limit Order (High/Open)", "Close Price (EOD)"),
            index=mode_idx,
            help="Limit: 고가가 목표가 도달 시 즉시 매도 / Close: 종가 기준으로 수익률 체크"
        )
        new_sell_mode = 'limit' if "Limit" in sell_mode_label else 'close'
        
        # Cash Buffer
        st.markdown("---")
        st.markdown("#### 💰 현금 버퍼 (Cash Buffer)")
        new_buffer = st.slider(
            "Cash Reserve (%)", 0, 50, 
            value=int(config.get("cash_buffer_pct", 0)), 
            step=5,
            help="포트폴리오의 일정 비중을 항상 현금으로 보유합니다."
        )
        if new_buffer > 0:
            st.info(f"💡 예상 효과: MDD ~{new_buffer*0.8:.0f}% 감소 / 수익률 ~{new_buffer}% 감소")

    # --- Trend Filter ---
    st.divider()
    c_kb1, c_kb2 = st.columns([1, 1])
    with c_kb1:
        use_ma = st.checkbox("이동평균선(MA) 추세 필터 사용", value=config.get('use_ma_filter', False))
    with c_kb2:
        ma_period = st.number_input("MA 기간 (일)", value=int(config.get('ma_period', 200)), step=10)
        
    ma_mode = st.radio(
        "MA 필터 동작 모드",
        options=["defensive", "pause"],
        index=0 if config.get('ma_mode', 'defensive') == 'defensive' else 1,
        format_func=lambda x: "🛡️ 전량 매도 (Defensive Sell)" if x == "defensive" else "⏸️ 신규 매수 중지 (Pause Buying)"
    )
    
    # --- Buy Limit Configuration ---
    st.divider()
    st.subheader("매수 제한 설정 (Risk Management)")
    c_lim1, c_lim2 = st.columns(2)
    with c_lim1:
        max_buys_day = st.number_input(
            "일일 최대 매수 횟수 (Max/Day)", 
            value=int(config.get("max_buys_day", 0)), 
            min_value=0, 
            help="0 = 무제한. 하루에 실행할 최대 매수 횟수입니다."
        )
    with c_lim2:
        max_buys_week = st.number_input(
            "주간 최대 매수 횟수 (Max/Week)", 
            value=int(config.get("max_buys_week", 0)), 
            min_value=0, 
            help="0 = 무제한. 최근 7일(Rolling) 동안의 최대 매수 횟수입니다."
        )
        
    force_buy_days = st.number_input(
        "강제 매수 대기일 (Idle Days to Force Buy)",
        value=int(config.get("force_buy_days", 0)),
        min_value=0,
        help="0 = 끔. 설정한 기간(일) 동안 매수가 없으면 다음 단계를 강제로 매수합니다."
    )

    # --- Steps Configuration ---
    st.divider()
    st.subheader("5. 분할 매수 단계 설정 (Step Configuration)")
    
    # Initialize Steps Data (and recover if corrupted)
    if 'steps_df' not in st.session_state or not isinstance(st.session_state.steps_df, pd.DataFrame):
        st.session_state.steps_df = load_steps_data()
        
    # Initialize Snapshot if needed
    if 'steps_df_frozen' not in st.session_state:
        st.session_state.steps_df_frozen = st.session_state.steps_df.copy()

    # Buttons for Add/Delete
    b_col1, b_col2, _ = st.columns([1, 1, 5])
    with b_col1:
        if st.button("➕ 행 추가"):
            new_row = pd.DataFrame([[-5.0, 10.0, "SSO", 5.0]], columns=["Drop(%)", "Shift(%)", "Ticker", "Profit(%)"])
            st.session_state.steps_df = pd.concat([st.session_state.steps_df, new_row], ignore_index=True)
            st.session_state.steps_df_frozen = st.session_state.steps_df.copy() # Key: Update frozen on structural change
            save_steps_data(st.session_state.steps_df)
            st.rerun()
    with b_col2:
        if st.button("🗑️ 마지막 행 삭제"):
            if len(st.session_state.steps_df) > 0:
                st.session_state.steps_df = st.session_state.steps_df.iloc[:-1]
                st.session_state.steps_df_frozen = st.session_state.steps_df.copy() # Key: Update frozen on structural change
                save_steps_data(st.session_state.steps_df)
                st.rerun()

    # Use Frozen DF for input to prevent widget reset on edit
    # Fix: Ensure frozen DF is up to date if the editor is being re-mounted (e.g. tab switch)
    if "steps_editor_main" not in st.session_state:
        st.session_state.steps_df_frozen = st.session_state.steps_df.copy()

    edited_df = st.data_editor(
        st.session_state.steps_df_frozen,
        num_rows="fixed", 
        use_container_width=True,
        key="steps_editor_main"
    )
    
    # Sync Logic: Update Global State + Disk, but NOT Frozen Input (preserves focus)
    if not edited_df.equals(st.session_state.steps_df):
        # Auto-correction: Ensure 'Drop(%)' is always negative
        if 'Drop(%)' in edited_df.columns:
            edited_df['Drop(%)'] = -edited_df['Drop(%)'].abs()
            
        st.session_state.steps_df = edited_df
        save_steps_data(edited_df)
    
    # --- Save Action ---
    st.divider()
    if st.button("💾 설정 저장 (Save Config)", type="primary", use_container_width=True):
        updated_config = {
            "base_ticker": new_base,
            "add_tickers": new_adds,
            "initial_capital": new_cap,
            "start_date": new_start.strftime("%Y-%m-%d"),
            "end_date": new_end.strftime("%Y-%m-%d"),
            "sell_mode": new_sell_mode,
            "cash_buffer_pct": new_buffer,
            "use_ma_filter": use_ma,
            "ma_mode": ma_mode,
            "ma_period": ma_period,
            "max_buys_day": max_buys_day,
            "max_buys_week": max_buys_week,
            "force_buy_days": force_buy_days
        }
        save_config(updated_config)
        save_steps_data(st.session_state.steps_df) # Explicit Save Steps
        st.session_state.config = updated_config
        st.success("설정이 저장되었습니다!")

