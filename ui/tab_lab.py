import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import io
from datetime import datetime
from analysis_logic import run_simulation
from utils import load_steps_data, save_config, save_steps_data

# --- Helper: Parse Excel String to Steps List ---
def parse_steps_from_string(drops_str, shits_str, tickers_str, profits_str):
    try:
        # 1. Parse into lists
        drops = [float(x) for x in str(drops_str).split(',')]
        shifts = [float(x) for x in str(shits_str).split(',')]
        tickers = [x.strip() for x in str(tickers_str).split(',')]
        profits = [float(x) for x in str(profits_str).split(',')]
        
        # 2. Normalize length (max length)
        max_len = max(len(drops), len(shifts), len(tickers), len(profits))
        
        steps = []
        for i in range(max_len):
            d = drops[i] if i < len(drops) else (drops[-1] if drops else -5.0)
            s = shifts[i] if i < len(shifts) else (shifts[-1] if shifts else 10.0)
            t = tickers[i] if i < len(tickers) else (tickers[-1] if tickers else "SSO")
            p = profits[i] if i < len(profits) else (profits[-1] if profits else 5.0)
            
            steps.append({
                "drop_pct": float(d),
                "shift_pct": float(s),
                "ticker": t,
                "profit_pct": float(p)
            })
        return steps
    except:
        return []

def render():
    st.header("🧪 실험실 (Experiment Lab)")
    st.info("다양한 시나리오를 설정하고 한 번에 실행하여 결과를 비교해보세요.")

    # --- Session State for Scenarios ---
    if 'lab_scenarios' not in st.session_state:
        st.session_state.lab_scenarios = []
    
    # --- 1. Excel Import / Template ---
    with st.expander("📥 엑셀로 시나리오 업로드 (Bulk Upload)", expanded=True):
        col_up1, col_up2 = st.columns([1, 2])
        
        with col_up1:
            st.markdown("**1. 템플릿 다운로드**")
            # Create Template DF
            tpl_data = [{
                "ScenarioName": "Aggressive_V1",
                "BaseTicker": "QQQ",
                "AddTickers": "TQQQ",
                "Capital": 10000,
                "CashBuffer": 0,
                "StartDate": "2025-01-01",
                "EndDate": datetime.today().strftime('%Y-%m-%d'),
                "MA_Filter": False,
                "MA_Mode": "defensive",
                "MA_Period": 200,
                "Step_Drops": "-5, -10, -15, -20",
                "Step_Shift": "10, 20, 30, 40",
                "Step_Tickers": "SSO, SSO, UPRO, UPRO",
                "Step_Profits": "5, 5, 10, 10"
            }]
            df_tpl = pd.DataFrame(tpl_data)
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_tpl.to_excel(writer, index=False)
                
            st.download_button(
                label="📄 템플릿 받기 (xlsx)",
                data=buffer.getvalue(),
                file_name="lab_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
        with col_up2:
            st.markdown("**2. 파일 업로드**")
            upl_file = st.file_uploader("작성한 엑셀 파일을 여기에 드롭하세요.", type=['xlsx'])
            
            if upl_file:
                # Prevent duplicate processing on reruns
                file_key = f"{upl_file.name}_{upl_file.size}"
                
                if st.session_state.get('lab_last_upload_key') != file_key:
                    try:
                        df_up = pd.read_excel(upl_file)
                        # Process
                        new_count = 0
                        for _, row in df_up.iterrows():
                             # Parse Steps
                            p_steps = parse_steps_from_string(
                                row.get('Step_Drops', '-5'),
                                row.get('Step_Shift', '10'),
                                row.get('Step_Tickers', 'SSO'),
                                row.get('Step_Profits', '5')
                            )
                            
                            # Retrieve MA settings if present
                            use_ma_val = row.get('MA_Filter', False)
                            # Handle string 'TRUE'/'FALSE' or 1/0 from Excel
                            if isinstance(use_ma_val, str):
                                use_ma_val = True if use_ma_val.lower() in ['true', 'yes', '1'] else False
                            elif isinstance(use_ma_val, (int, float)):
                                use_ma_val = bool(use_ma_val)
                            
                            ma_period_val = int(row.get('MA_Period', 200))
                            ma_mode_val = str(row.get('MA_Mode', 'defensive')).lower().strip()
                            if ma_mode_val not in ['defensive', 'pause']: ma_mode_val = 'defensive'
                            
                            # Risk Params
                            max_buys_day_val = int(row.get('MaxBuysDay', 0))
                            max_buys_week_val = int(row.get('MaxBuysWeek', 0))
                            force_buy_days_val = int(row.get('ForceBuyDays', 0))

                            sc_conf = {
                                "scenario_name": row.get("ScenarioName", f"Upload_{new_count}"),
                                "base_ticker": row.get("BaseTicker", "QQQ"),
                                "add_tickers": row.get("AddTickers", "TQQQ"),
                                "initial_capital": int(row.get("Capital", 10000)),
                                "cash_buffer_pct": float(row.get("CashBuffer", 0)),
                                "start_date": str(row.get("StartDate", "2025-01-01")).split()[0], # Safe parse
                                "end_date": str(row.get("EndDate", datetime.today().strftime('%Y-%m-%d'))).split()[0],
                                "sell_mode": str(row.get('SellMode', st.session_state.get('config', {}).get('sell_mode', 'limit'))),
                                "use_ma_filter": use_ma_val,
                                "ma_mode": ma_mode_val,
                                "ma_period": ma_period_val,
                                "max_buys_day": max_buys_day_val,
                                "max_buys_week": max_buys_week_val,
                                "force_buy_days": force_buy_days_val
                            }
                            
                            st.session_state.lab_scenarios.append({
                                "name": sc_conf["scenario_name"],
                                "config": sc_conf,
                                "steps_list": p_steps
                            })
                            new_count += 1
                            
                        st.session_state.lab_last_upload_key = file_key
                        st.success(f"{new_count} Scenarios Loaded!")
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Error parsing Excel: {e}")
                else:
                    # File exists but already processed. If Queue is empty, offer reload.
                    if not st.session_state.lab_scenarios:
                        if st.button("🔄 파일 다시 읽기 (Reload File)"):
                            st.session_state['lab_last_upload_key'] = None
                            st.rerun()

    st.divider()
    
    # --- 2. Manual Add Interface ---
    with st.expander("➕ 직접 시나리오 추가 (Manual Add)", expanded=False):
        col1, col2 = st.columns(2)
        
        # Load Defaults from Main Config
        base_conf = st.session_state.get('config', {})
        
        with col1:
            sc_name = st.text_input("시나리오 이름", value=f"Scenario {len(st.session_state.lab_scenarios)+1}", key="lab_name")
            sc_base = st.text_input("Base Ticker", value=base_conf.get('base_ticker', 'QQQ'), key="lab_base")
            sc_add = st.text_input("Add Tickers", value=base_conf.get('add_tickers', 'TQQQ'), key="lab_add")
            sc_cap = st.number_input("Capital ($)", value=base_conf.get('initial_capital', 10000), key="lab_cap")
            
            # Risk Inputs
            sc_max_day = st.number_input("Max Buys/Day", value=int(base_conf.get('max_buys_day', 0)), key="lab_m_day")
            sc_max_week = st.number_input("Max Buys/Week", value=int(base_conf.get('max_buys_week', 0)), key="lab_m_week")
            sc_force = st.number_input("Force Buy Days", value=int(base_conf.get('force_buy_days', 0)), key="lab_m_force")
            
        with col2:
            sc_buffer = st.slider("Cash Buffer (%)", 0, 50, value=int(base_conf.get('cash_buffer_pct', 0)), key="lab_buffer")
            
            # MA Filter UI
            c_ma1, c_ma2, c_ma3 = st.columns([1,1,1])
            with c_ma1:
                sc_use_ma = st.checkbox("MA Filter", value=base_conf.get('use_ma_filter', False), key="lab_use_ma")
            with c_ma2:
                sc_ma_mode = st.selectbox("Mode", ["defensive", "pause"], index=0 if base_conf.get('ma_mode', 'defensive') == 'defensive' else 1, key="lab_ma_mode")
            with c_ma3:
                sc_ma_period = st.number_input("Period", value=int(base_conf.get('ma_period', 200)), step=10, key="lab_ma_pd")
                
            sc_start = st.date_input("Start Date", 
                                     value=datetime.strptime(str(base_conf.get('start_date', '2025-01-01')).split()[0], "%Y-%m-%d"), 
                                     min_value=datetime(1990, 1, 1), max_value=datetime.today(), key="lab_start")
            sc_end = st.date_input("End Date", 
                                   value=datetime.strptime(str(base_conf.get('end_date', datetime.today().strftime('%Y-%m-%d'))).split()[0], "%Y-%m-%d"), 
                                   min_value=datetime(1990, 1, 1), max_value=datetime.today(), key="lab_end")
        
        # Steps
        st.markdown("**Step Configuration**")
        use_current_steps = st.checkbox("현재 설정(Settings 탭)의 스텝 사용", value=True, key="lab_use_curr_steps")
        
        if st.button("📥 리스트에 추가 (Add to Queue)", key="lab_add_btn"):
            if use_current_steps:
                # Convert DF to list of dicts
                curr_steps_df = st.session_state.get('steps_df', load_steps_data())
                steps_list = []
                for _, r in curr_steps_df.iterrows():
                    steps_list.append({
                        "drop_pct": float(r["Drop(%)"]),
                        "shift_pct": float(r["Shift(%)"]),
                        "ticker": r["Ticker"],
                        "profit_pct": float(r["Profit(%)"])
                    })
            else:
                steps_list = [] # Empty means no steps? Or default?

            new_scenario = {
                "id": len(st.session_state.lab_scenarios),
                "name": sc_name,
                "config": {
                    "base_ticker": sc_base,
                    "add_tickers": sc_add,
                    "initial_capital": sc_cap,
                    "cash_buffer_pct": sc_buffer,
                    "start_date": sc_start.strftime("%Y-%m-%d"),
                    "end_date": sc_end.strftime("%Y-%m-%d"),
                    "sell_mode": base_conf.get('sell_mode', 'limit'),
                    "use_ma_filter": sc_use_ma,
                    "ma_mode": sc_ma_mode,
                    "ma_period": sc_ma_period,
                    "max_buys_day": sc_max_day,
                    "max_buys_week": sc_max_week,
                    "force_buy_days": sc_force,
                },
                "steps_list": steps_list
            }
            st.session_state.lab_scenarios.append(new_scenario)
            st.success(f"Added '{sc_name}'!")


    # 2. Scenario Queue
    st.divider()
    st.subheader(f"대기열 (Queue): {len(st.session_state.lab_scenarios)}개")
    
    # Show queue table (Always show, even if empty)
    queue_data = []
    for s in st.session_state.lab_scenarios:
        # Generate Recipe String
        recipe_str = "Default"
        steps = s.get('steps_list', s.get('steps'))
        
        if isinstance(steps, list) and steps:
            drops = [str(x['drop_pct']) for x in steps]
            tickers = [str(x['ticker']) for x in steps]
            profits = [str(x['profit_pct']) for x in steps]
            # Compact Summary
            recipe_str = f"Drop[{','.join(drops)}] Ticker[{','.join(tickers)}] Profit[{','.join(profits)}]"
            
        ma_info = "OFF"
        if s['config'].get('use_ma_filter'):
            ma_info = f"{s['config'].get('ma_mode', 'defensive')}/{s['config'].get('ma_period')}"

        queue_data.append({
            "Name": s['name'],
            "Buffer": f"{s['config']['cash_buffer_pct']}%",
            "MA": ma_info,
            "Tickers": f"{s['config']['base_ticker']} + {s['config']['add_tickers']}",
            "Recipe": recipe_str,
            "Start": s['config']['start_date'],
            "End": s['config']['end_date']
        })
    
    st.dataframe(
        pd.DataFrame(queue_data), 
        use_container_width=True,
        column_config={
            "Name": st.column_config.TextColumn("Scenario Name", width="medium"),
            "MA": st.column_config.TextColumn("MA Filter", width="small"),
            "Recipe": st.column_config.TextColumn("Steps Config", width="large"),
        }
    )

    with st.expander("🔍 시나리오 상세 설정 확인 (Debug Info)"):
        st.json(st.session_state.lab_scenarios)

    
    c1, c2 = st.columns([1, 4])
    with c1:
        if st.button("🧹 초기화 (Clear)"):
            st.session_state.lab_scenarios = []
            st.session_state.lab_results = []
            st.session_state['lab_last_upload_key'] = None # Allow re-upload
            st.rerun()
            
    with c2:
        is_empty = len(st.session_state.lab_scenarios) == 0
        if st.button("🚀 전체 실행 (Run Batch)", type="primary", disabled=is_empty):
            results_container = []
            
            progress_text = "Operation in progress. Please wait."
            my_bar = st.progress(0, text=progress_text)
            
            for i, sc in enumerate(st.session_state.lab_scenarios):
                my_bar.progress((i) / len(st.session_state.lab_scenarios), text=f"Running {sc['name']}...")
                
                # Support both new List and old DataFrame formats
                steps_input = sc.get('steps_list', sc.get('steps'))
                res, summ, annual, bt = run_simulation(sc['config'], steps_input)
                
                if res is not None:
                    results_container.append({
                        "scenario": sc,
                        "results": res,
                        "summary": summ,
                        "annual": annual
                    })
            
            my_bar.empty()
            st.session_state.lab_results = results_container
            st.success("Batch Analysis Complete!")

    # 3. Compare Results
    if 'lab_results' in st.session_state and st.session_state.lab_results:
        st.divider()
        st.subheader("🏆 결과 비교 (Comparison)")
        
        lab_res = st.session_state.lab_results
        
        # Table Comparison
        comp_rows = []
        for r in lab_res:
            summ = r['summary']
            sc = r['scenario']
            comp_rows.append({
                "Load": False, # Trigger for loading this scenario
                "Scenario": sc['name'],
                "CAGR": summ['CAGR'],
                "MDD": summ['MDD'],
                "Total Return": summ['Total Return'],
                "Trades": summ.get('Trade Count', 0),
                "Rebalance": summ.get('Rebalance Count', 0),
                "BH Return": summ['BH Return'],
                "BH MDD": summ['BH MDD']
            })
        
        comp_df = pd.DataFrame(comp_rows)
        
        # Use DataEditor for Load Interaction
        edited_comp = st.data_editor(
            comp_df,
            key="lab_results_editor",
            use_container_width=True,
            column_config={
                "Load": st.column_config.CheckboxColumn("Load", width="small", help="Check to load this strategy settings"),
                "Scenario": st.column_config.TextColumn("Scenario", width="medium"),
                "Trades": st.column_config.NumberColumn("Trades #", format="%d"), 
                "Rebalance": st.column_config.NumberColumn("Rebal #", format="%d"), 
            },
            disabled=["Scenario", "CAGR", "MDD", "Total Return", "Rebalance", "Buffer"],
            hide_index=True
        )
        
        # Check for Load Trigger
        if edited_comp['Load'].any():
            # Find which index was checked
            sel_idx = edited_comp.index[edited_comp['Load']].tolist()[0]
            
            # Get Scenario
            target_res = lab_res[sel_idx]
            target_sc = target_res['scenario']
            
            # Load Params
            new_config = target_sc['config']
            new_steps = target_sc['steps_list'] if 'steps_list' in target_sc else target_sc.get('steps', [])
            
            # Convert Steps to DF
            if isinstance(new_steps, list):
                # Standardize keys if needed, assuming list of dicts consistent with parse
                steps_df = pd.DataFrame(new_steps)
                # Ensure columns match expected
                expected_cols = ["drop_pct", "shift_pct", "ticker", "profit_pct"]
                # Map keys if slightly different? Usually 'drop_pct' etc from loader.
                
                # Rename for UI consistency (The UI uses Drop(%), Shift(%) etc in settings??)
                # Let's check utils.load_steps_data columns: ["Drop(%)", "Shift(%)", "Ticker", "Profit(%)"]
                # The lab loader likely produces "drop_pct" keys.
                
                # Map keys
                steps_df = steps_df.rename(columns={
                    "drop_pct": "Drop(%)",
                    "shift_pct": "Shift(%)",
                    "ticker": "Ticker",
                    "profit_pct": "Profit(%)"
                })
                # Select only relevant
                steps_df = steps_df[["Drop(%)", "Shift(%)", "Ticker", "Profit(%)"]]
            else:
                # If new_steps is not a list (e.g., already a DataFrame or empty), handle accordingly
                # For now, assume it's a list or empty. If it could be a DataFrame, more logic needed.
                steps_df = pd.DataFrame() # Default to empty if not list
            
            # Update Session State
            st.session_state.config = new_config
            st.session_state.steps_df = steps_df
            
            # Save to Disk
            save_config(new_config)
            save_steps_data(steps_df)
            
            st.toast(f"✅ 전략 '{target_sc['name']}' 설정이 로드되었습니다!", icon="📥")
            
            # Rerun to reset Checkbox (comp_rows rebuilt with False)
            st.rerun()
        
        # Chart Comparison
        st.subheader("📈 수익 곡선 비교 (Equity Curve Overlay)")
        
        fig = go.Figure()
        
        for r in lab_res:
            sc_name = r['scenario']['name']
            df_res = r['results']
            
            fig.add_trace(go.Scatter(
                x=df_res.index, 
                y=df_res['PortfolioValue'], 
                name=sc_name,
                mode='lines'
            ))
            
        fig.update_layout(height=600, template="plotly_white", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
