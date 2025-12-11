import streamlit as st
import pandas as pd
import os
import io
import json
from utils import HISTORY_FILE

def render():
    st.header("📜 시뮬레이션 기록 (History)")
    
    if os.path.exists(HISTORY_FILE):
        history_df = pd.read_csv(HISTORY_FILE)
        
        if not history_df.empty:
            # Sort desc
            history_df = history_df.sort_values('Timestamp', ascending=False).reset_index(drop=True)
            
            # --- Filtering ---
            with st.expander("🔍 필터 및 정렬 (Filter & Sort)", expanded=False):
                c1, c2 = st.columns(2)
                # Persist Filter State
                if 'h_min_cagr' not in st.session_state: st.session_state.h_min_cagr = -50
                if 'h_max_mdd' not in st.session_state: st.session_state.h_max_mdd = -100
                
                c1, c2 = st.columns(2)
                with c1:
                    min_cagr = st.slider("최소 CAGR (%)", -50, 100, 
                                       value=st.session_state.h_min_cagr, 
                                       key="w_min_cagr")
                    st.session_state.h_min_cagr = min_cagr
                with c2:
                    max_mdd = st.slider("최대 MDD (%)", -100, 0, 
                                      value=st.session_state.h_max_mdd, 
                                      key="w_max_mdd")
                    st.session_state.h_max_mdd = max_mdd
            
            # Helper to parse percentage strings
            def parse_pct(s):
                try:
                    return float(str(s).replace('%', ''))
                except:
                    return -999.0
            
            # Apply Filter
            # Create temp cols for filtering
            history_df['CAGR_Num'] = history_df['CAGR'].apply(parse_pct)
            history_df['MDD_Num'] = history_df['MDD'].apply(parse_pct)
            
            filtered_df = history_df[
                (history_df['CAGR_Num'] >= min_cagr) & 
                (history_df['MDD_Num'] >= max_mdd)
            ].copy()
            
            # Drop temp cols
            filtered_df = filtered_df.drop(columns=['CAGR_Num', 'MDD_Num'])
            
            st.write(f"총 {len(filtered_df)}개 기록 표시 중")
            
            # Selection UI
            filtered_df.insert(0, "Delete", False)
            filtered_df.insert(0, "Load", False)
            
            edited_hist = st.data_editor(
                filtered_df,
                hide_index=True,
                column_config={
                    "Load": st.column_config.CheckboxColumn(label="📂 Load", help="Check to load this setting", width="small"),
                    "Delete": st.column_config.CheckboxColumn(label="🗑️ Del", width="small")
                },
                disabled=[c for c in filtered_df.columns if c not in ["Delete", "Load"]],
                use_container_width=True,
                key="hist_editor"
            )
            
            # Action: Load
            to_load = edited_hist[edited_hist["Load"] == True]
            if not to_load.empty:
                # Load the first selected
                row = to_load.iloc[0]
                
                # 1. Update Config (Basic)
                new_config = {
                    "base_ticker": row.get('BaseTicker', 'QQQ'),
                    "add_tickers": row.get('AddTickers', 'TQQQ'),
                    "initial_capital": int(row.get('Capital', 10000)),
                    "start_date": str(row.get('StartDate', '2025-01-01')),
                    "end_date": str(row.get('EndDate', '2025-12-31')),
                    "sell_mode": row.get('SellMode', 'limit'),
                    "cash_buffer_pct": int(row.get('CashBuffer', 0)),
                    # Updated Load Logic for new params
                    "max_buys_day": int(row.get('MaxBuysDay', 0)),
                    "max_buys_week": int(row.get('MaxBuysWeek', 0)),
                    "force_buy_days": int(row.get('ForceBuyDays', 0)),
                    "use_ma_filter": bool(row.get('MA_Filter', False)),
                    "ma_mode": row.get('MA_Mode', 'defensive'),
                    "ma_period": int(row.get('MA_Period', 200)),
                }
                
                # 2. Update Steps
                s_conf = row.get('StepsConfig', '[]')
                if pd.isna(s_conf): s_conf = '[]'
                import ast
                try:
                    # JSON or List String
                    steps_data = json.loads(s_conf) if isinstance(s_conf, str) and s_conf.startswith('[') else s_conf
                    # Fallback for Python string rep
                    if isinstance(steps_data, str): 
                        try: steps_data = ast.literal_eval(steps_data)
                        except: steps_data = []
                except:
                    steps_data = []
                
                if isinstance(steps_data, list) and len(steps_data) > 0:
                    steps_df = pd.DataFrame(steps_data)
                    # Helper to normalize columns if needed
                    # Ensure col names match current
                    # History might have slightly different keys if schema changed, but normally 'drop_pct' etc.
                    # Current UI uses: Drop(%), Shift(%), Ticker, Profit(%)
                    # Engine uses: drop_pct, shift_pct, ticker, profit_pct
                    # We need to convert to UI format for display
                    
                    rename_map = {
                        'drop_pct': 'Drop(%)',
                        'shift_pct': 'Shift(%)',
                        'ticker': 'Ticker',
                        'profit_pct': 'Profit(%)'
                    }
                    steps_df.rename(columns=rename_map, inplace=True)
                    
                    # Fix Auto-Negative (just in case history has mixed)
                    if 'Drop(%)' in steps_df.columns:
                        steps_df['Drop(%)'] = -steps_df['Drop(%)'].abs()

                    st.session_state.steps_df = steps_df
                    from utils import save_steps_data
                    save_steps_data(steps_df)
                
                # 3. Save Config
                st.session_state.config = new_config
                from utils import save_config
                save_config(new_config)
                
                st.success(f"설정이 로드되었습니다! (Timestamp: {row['Timestamp']}) -> 설정 탭에서 확인하세요.")
                # Optional: Uncheck load? (Hard to do without rerun trickery, but rerun clears it since we reload DF from disk)
                # But we modified disk already? No, we modified 'config'. history file untouched.
                # So rerun resets UI state? Yes.
                st.rerun()

            # Action Buttons
            col_act1, col_act2, col_act3 = st.columns([1, 1, 1])
            
            # 1. Delete Selected
            to_delete = edited_hist[edited_hist["Delete"] == True]
            with col_act1:
                if not to_delete.empty:
                    if st.button(f"🗑️ 선택 {len(to_delete)}개 삭제", type="primary"):
                        timestamps_to_del = to_delete['Timestamp'].tolist()
                        new_df = history_df[~history_df['Timestamp'].isin(timestamps_to_del)]
                        new_df.to_csv(HISTORY_FILE, index=False)
                        st.success("Deleted!")
                        st.rerun()

            # 2. Delete All Filtered
            with col_act2:
                if not filtered_df.empty:
                    if st.button(f"⚠️ 필터 목록 전체 삭제 ({len(filtered_df)}개)", type="secondary"):
                        timestamps_to_del = filtered_df['Timestamp'].tolist()
                        new_df = history_df[~history_df['Timestamp'].isin(timestamps_to_del)]
                        new_df.to_csv(HISTORY_FILE, index=False)
                        st.success("All Filtered Deleted!")
                        st.rerun()
                        
            # 3. Export as Recipe (Recipe Generator)
            with col_act3:
                if not filtered_df.empty:
                    # Logic to convert filtered_df to Lab Excel format
                    recipe_rows = []
                    for idx, row in filtered_df.iterrows():
                        # Parse Steps JSON
                        try:
                            # If it's a string, parse it. If it's Nan/None, skip
                            s_conf = row.get('StepsConfig', '[]')
                            if pd.isna(s_conf): s_conf = '[]'
                            
                            steps_data = json.loads(s_conf) if isinstance(s_conf, str) else s_conf
                            
                            # Construct step strings
                            # Ensure we handle list of dicts properly
                            drops = [str(s.get('Drop(%)', s.get('drop_pct', 0))) for s in steps_data]
                            shifts = [str(s.get('Shift(%)', s.get('shift_pct', 0))) for s in steps_data]
                            tickers = [str(s.get('Ticker', s.get('ticker', ''))) for s in steps_data]
                            profits = [str(s.get('Profit(%)', s.get('profit_pct', 0))) for s in steps_data]
                            
                            recipe_rows.append({
                                "ScenarioName": f"Hist_{row['Timestamp']}", # Unique Name
                                "BaseTicker": row.get('BaseTicker', 'QQQ'),
                                "AddTickers": row.get('AddTickers', 'TQQQ'),
                                "Capital": row.get('Capital', 10000),
                                "CashBuffer": row.get('CashBuffer', 0),
                                "StartDate": row.get('StartDate', '2025-01-01'),
                                "EndDate": row.get('EndDate', '2025-12-31'),
                                "SellMode": row.get('SellMode', 'limit'),
                                # Updated Export Logic for new params
                                "MaxBuysDay": row.get('MaxBuysDay', 0),
                                "MaxBuysWeek": row.get('MaxBuysWeek', 0),
                                "ForceBuyDays": row.get('ForceBuyDays', 0),
                                "MA_Filter": row.get('MA_Filter', False), 
                                "MA_Mode": row.get('MA_Mode', 0),
                                "MA_Period": row.get('MA_Period', 200),
                                "Step_Drops": ", ".join(drops),
                                "Step_Shift": ", ".join(shifts),
                                "Step_Tickers": ", ".join(tickers),
                                "Step_Profits": ", ".join(profits),
                                # Result Metadata (Ignored by Lab import)
                                "Result_CAGR": row.get('CAGR'),
                                "Result_MDD": row.get('MDD')
                            })
                        except Exception as e:
                            # Skip row if parse fails
                            continue
                    
                    if recipe_rows:
                        # Create Excel
                        df_recipe = pd.DataFrame(recipe_rows)
                        buffer = io.BytesIO()
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                            df_recipe.to_excel(writer, index=False)
                            
                        st.download_button(
                            label="💾 필터 결과 엑셀로 저장 (to Lab)",
                            data=buffer.getvalue(),
                            file_name=f"recipe_from_history_{len(recipe_rows)}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )

        else:
            st.info("기록이 없습니다.")
    else:
        st.info("저장된 시뮬레이션 기록이 없습니다.")
