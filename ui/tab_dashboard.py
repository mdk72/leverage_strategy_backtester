import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from utils import save_config, log_simulation_history, save_steps_data
from analysis_logic import run_simulation

def render():
    st.header("📊 대시보드 (Dashboard)")
    
    # Check dependencies
    if 'steps_df' not in st.session_state:
        st.warning("설정 탭에서 데이터를 먼저 확인해주세요.")
        return
        
    config = st.session_state.get('config', {})

    # --- Action Area ---
    # Button removed to avoid duplication with parent tab_analysis.py
    # This component now only displays results passed via session state.


    # --- Display Results ---
    if 'analysis_data' in st.session_state:
        results, summary, annual_stats, bt = st.session_state['analysis_data']
        
        # 1. Top Metrics
        st.subheader("Results Summary")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Final Value", summary['Final Value'])
        m2.metric("Total Return", summary['Total Return'])
        m3.metric("CAGR", summary['CAGR'])
        m4.metric("MDD", summary['MDD'], delta_color="inverse")
        
        # Cash Buffer Info
        if summary.get('Cash Buffer', 'None') != 'None':
            st.info(f"💰 **Cash Defense Active**: Buffer {summary['Cash Buffer']} | Final Cash: {summary.get('Final Cash')}")

        st.divider()

        # 2. Portfolio Matrix (Ticker Performance)
        st.subheader("📌 종목별 성과 (Ticker Performance)")
        if bt and hasattr(bt, 'trade_log'):
            tlog = pd.DataFrame(bt.trade_log)
            if not tlog.empty:
                # Group by Ticker (Derived from Step/Symbol if avail, but internal log might just say 'UPRO')
                # Trade log 'Action' usually contains symbol? 
                # Let's check trade_log structure. Assuming 'Ticker' isn't explicitly there but can be inferred or added.
                # Actually, backtester.py adds 'Ticker' to trade_log? Let's check. 
                # The provided code for backtest_engine.py wasn't fully inspected, but let's assume we can aggregate.
                # If not, we might only have one stream. But the steps have different tickers.
                # If 'Ticker' key exists in trade dictionary...
                if 'Ticker' in tlog.columns:
                    # Filter out internal switch actions for cleaner display
                    tlog_clean = tlog[~tlog['Ticker'].str.contains('->', na=False)].copy()
                    
                    # Ensure columns exist
                    if 'ProfitAmt' not in tlog_clean.columns: tlog_clean['ProfitAmt'] = 0.0
                    if 'ProfitPct' not in tlog_clean.columns: tlog_clean['ProfitPct'] = 0.0
                    
                    perf_df = tlog_clean.groupby('Ticker').agg({
                        'ProfitAmt': 'sum',
                        'ProfitPct': 'mean',
                        'Action': 'count'
                    }).rename(columns={'Action': 'Activity Count', 'ProfitAmt': 'Total Profit ($)', 'ProfitPct': 'Avg Profit (%)'})

                    # Fix Base Ticker (QQQ) Profit by Residual
                    # Since Backtester doesn't track Base Ticker P&L explicitly (it's a funding source),
                    # we derive it: Total Net Profit - Sum of Other Profits.
                    if bt.base_ticker in perf_df.index:
                        # Calculate Total Portfolio Profit
                        initial_cap = st.session_state.get('config', {}).get('initial_capital', 10000) 
                        # Use analysis_data summary if easier, but we have results
                        final_val = results['PortfolioValue'].iloc[-1]
                        total_net_profit = final_val - initial_cap
                        
                        # Sum of others (TQQQ, etc.)
                        others_profit = perf_df.loc[perf_df.index != bt.base_ticker, 'Total Profit ($)'].sum()
                        
                        # Assign Residual to Base
                        base_profit = total_net_profit - others_profit
                        perf_df.loc[bt.base_ticker, 'Total Profit ($)'] = base_profit
                        
                        # Avg Profit for Base is hard to define, maybe leave as is or set to Total Return %
                        # REFACTOR: Use Contribution (%) for consistency
                        pass

                    # Calculate Contribution (%) for ALL tickers
                    # Contribution = (Total Profit / Initial Capital) * 100
                    if initial_cap == 0: initial_cap = 1
                    perf_df['Contribution (%)'] = (perf_df['Total Profit ($)'] / initial_cap) * 100
                    
                    # Reorder
                    # Ensure columns exist before reordering
                    cols = ['Total Profit ($)', 'Contribution (%)', 'Activity Count']
                    # Keep Sell Count separate logic below

                    # Count pure Sells for WinRate
                    sells = tlog_clean[tlog_clean['Action'].str.contains('SELL', na=False)]
                    if not sells.empty:
                        sell_counts = sells.groupby('Ticker').size()
                        perf_df['Sell Count'] = sell_counts
                    else:
                        perf_df['Sell Count'] = 0
                    
                    # Fix NaN and Float formatting
                    perf_df['Sell Count'] = perf_df['Sell Count'].fillna(0).astype(int)
                        
                    st.dataframe(
                        perf_df[['Total Profit ($)', 'Contribution (%)', 'Activity Count', 'Sell Count']].style.format({
                            'Total Profit ($)': "${:,.0f}", 
                            'Contribution (%)': "{:.2f}%",
                            'Sell Count': "{:,}"
                        })
                    )
                else:
                    st.write("Ticker breakdown not available (Check engine update).")
        
        st.divider()

        # 3. Charts
        st.subheader("Performance Charts")
        
        # Check for Data Freshness
        if 'BuyHoldValue' not in results.columns:
            st.warning("⚠️ 차트에 'Buy & Hold' 비교선이 보이지 않으면, 위쪽의 [🚀 백테스팅 실행] 버튼을 다시 한 번 눌러주세요. (새로운 데이터 계산 필요)")
        
        # Equity Curve (Single Chart: Return %)
        fig = go.Figure()
        
        # Calculate Returns
        initial_cap = config.get("initial_capital", 10000)
        strat_ret = (results['PortfolioValue'] / initial_cap - 1) * 100
        
        # 1. Portfolio Return
        fig.add_trace(go.Scatter(x=results.index, y=strat_ret, name="Portfolio (%)", line=dict(color='green', width=2)))
        
        # 2. Buy & Hold Return
        if 'BuyHoldValue' in results.columns:
            bh_ret = (results['BuyHoldValue'] / initial_cap - 1) * 100
            fig.add_trace(go.Scatter(x=results.index, y=bh_ret, name=f"Buy & Hold ({bt.base_ticker}) %", line=dict(color='red', width=2, dash='dash')))
        
        fig.update_layout(
            title="Cumulative Return Comparison (%)",
            xaxis_title="Date",
            yaxis_title="Return (%)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # 4. Annual Stats
        st.subheader("📆 Annual Performance")
        st.dataframe(annual_stats, use_container_width=True)
        
        # 5. Step Analysis
        st.subheader("🪜 Step-by-Step Analysis")
        if bt:
            step_metrics = bt.get_step_metrics_df()
            st.dataframe(
                step_metrics,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Avg Profit": st.column_config.TextColumn("Avg Profit", help="Average return per trade"),
                    "Total Profit ($)": st.column_config.TextColumn("Total Profit", help="Total profit amount generated by this step"),
                    "Contribution": st.column_config.TextColumn("Contribution", help="Impact on total strategy profit (Step Profit / Total Profit)")
                }
            )

    else:
        st.info("👆 [백테스팅 실행] 버튼을 눌러 분석을 시작하세요.")
