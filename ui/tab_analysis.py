import streamlit as st
import pandas as pd
from analysis_logic import run_simulation
from ui import tab_dashboard, tab_history
from utils import load_config, load_steps_data, log_simulation_history

def render():
    st.title("📈 AI 상세 분석 (AI Analysis)")
    
    # Run Button
    if st.button("🚀 시뮬레이션 실행", type="primary"):
        # Load Config & Steps
        disk_config = load_config()
        
        # Merge with session state config if available (prefer session state for immediate changes)
        if 'config' in st.session_state:
            config = {**disk_config, **st.session_state.config}
        else:
            config = disk_config
            
            
        # Prefer session state steps if available (synced from Settings tab)
        if 'steps_df' in st.session_state and isinstance(st.session_state.steps_df, pd.DataFrame):
            steps_input = st.session_state.steps_df
        else:
            steps_input = load_steps_data()

        # Run Simulation
        # run_simulation returns: results, summary, annual_stats, bt
        run_res = run_simulation(config, steps_input)
        
        # Unpack safely
        if run_res[0] is not None:
            results, summary, annual_stats, bt = run_res
            
            # Store results in Session State for Dashboard/History tabs to access
            st.session_state['analysis_data'] = (results, summary, annual_stats, bt)
            
            # Legacy support if needed
            st.session_state.results = results
            st.session_state.summary = summary
            st.session_state.daily_stats = results
            st.session_state.trade_log = bt.trade_log
            
            # --- Save History Log ---
            try:
                # Serialize Steps
                steps_summary_str = "; ".join([f"{s['drop_pct']}%/{s['shift_pct']}%" for s in bt.steps])
                steps_config_json = steps_input.to_json(orient='records') if isinstance(steps_input, pd.DataFrame) else str(steps_input)
                
                params = {
                    "BaseTicker": config.get("base_ticker"),
                    "AddTickers": config.get("add_tickers"),
                    "Capital": config.get("initial_capital"),
                    "CashBuffer": config.get("cash_buffer_pct"),
                    "StartDate": config.get("start_date"),
                    "EndDate": config.get("end_date"),
                    "SellMode": config.get("sell_mode"),
                    "Steps": steps_summary_str,
                    "StepsConfig": steps_config_json,
                    # Added missing params
                    "MaxBuysDay": config.get("max_buys_day", 0),
                    "MaxBuysWeek": config.get("max_buys_week", 0),
                    "ForceBuyDays": config.get("force_buy_days", 0),
                    "MA_Filter": config.get("use_ma_filter", False),
                    "MA_Mode": config.get("ma_mode", "defensive"),
                    "MA_Period": config.get("ma_period", 200)
                }
                
                res_log = {
                    "FinalValue": summary.get('Final Value'),
                    "TotalReturn": summary.get('Total Return'),
                    "CAGR": summary.get('CAGR'),
                    "MDD": summary.get('MDD'),
                    "TradeCount": summary.get('Trade Count'),
                    "FinalCash": summary.get('Final Cash', '$0'),
                    "RebalanceCount": summary.get('Rebalance Count', 0)
                }
                
                log_simulation_history(params, res_log)
                st.success("시뮬레이션 완료 및 기록 저장됨! (Saved to History)")
                
            except Exception as e:
                st.warning(f"시뮬레이션은 완료되었으나, 기록 저장 중 오류 발생: {e}")
                
        else:
            st.error("시뮬레이션 실패.")
            
    # Sub-tabs for Analysis
    t1, t2 = st.tabs(["📊 대시보드", "📜 매매 일지"])
    
    with t1:
        if 'analysis_data' in st.session_state:
            tab_dashboard.render()
        else:
            st.info("실행 버튼을 눌러주세요.")
            
    with t2:
        if 'trade_log' in st.session_state and st.session_state.trade_log:
            # Inline Rendering of Trade Log
            tlog_df = pd.DataFrame(st.session_state.trade_log)
            
            # Type Conversion
            if 'Date' in tlog_df.columns:
                tlog_df['Date'] = pd.to_datetime(tlog_df['Date']).dt.strftime('%Y-%m-%d')
            if 'Price' in tlog_df.columns:
                tlog_df['Price'] = pd.to_numeric(tlog_df['Price'], errors='coerce')
            if 'Value' in tlog_df.columns:
                tlog_df['Value'] = pd.to_numeric(tlog_df['Value'], errors='coerce')

            # Filter Skips optional?
            show_all = st.checkbox("SKIP(Limit) 포함 보기", value=False, key="an_show_skips")
            if not show_all and 'Action' in tlog_df.columns:
                tlog_df = tlog_df[~tlog_df['Action'].str.contains("SKIP")]
                
            st.dataframe(
                tlog_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Date": st.column_config.DatetimeColumn("Date", format="YYYY-MM-DD"),
                    "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
                    "Value": st.column_config.NumberColumn("Value", format="$%.2f"),
                }
            )
        else:
            st.info("시뮬레이션 데이터가 없습니다.")
