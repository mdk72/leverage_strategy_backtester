import streamlit as st
import pandas as pd
from datetime import timedelta, datetime
from backtest_engine import Backtester
from data_loader import fetch_and_process_data
import os

# --- Helper: Ticker Resolution ---
def resolve_ticker(t_input):
    t_clean = t_input.strip()
    # Common Mapping
    mapping = {
        "KODEX 코스피100": "237350.KS",
        "KODEX 레버리지": "122630.KS",
        "KODEX 200": "069500.KS",
        "KODEX 인버스": "114800.KS",
        "KODEX 200선물인버스2X": "252670.KS",
        "TIGER 미국S&P500": "360750.KS",
        "TIGER 미국나스닥100": "371460.KS"
    }
    
    # 1. Check Mapping
    if t_clean in mapping:
        return mapping[t_clean]
        
    # 2. Check 6-digit code (Korean Stock)
    if t_clean.isdigit() and len(t_clean) == 6:
        return f"{t_clean}.KS"
        
    # 3. Default (Upper case)
    return t_clean.upper()

def run_simulation(config, steps_input):
    """
    Executes the backtest simulation based on config and steps.
    steps_input: Can be a pd.DataFrame (from UI) or a list of dicts (from Lab/Excel)
    Returns: (results, summary, annual_stats, backtester_instance) or (None, None, None, None)
    """
    # 1. Parse Config
    base_ticker = config.get("base_ticker", "QQQ")
    add_tickers_str = config.get("add_tickers", "TQQQ")
    initial_capital = config.get("initial_capital", 10000)
    start_date_str = config.get("start_date", "2025-01-01")
    end_date_str = config.get("end_date", datetime.today().strftime("%Y-%m-%d"))
    sell_mode = config.get("sell_mode", "limit")
    cash_buffer_pct = config.get("cash_buffer_pct", 0)
    use_ma = config.get("use_ma_filter", False)
    ma_mode = config.get("ma_mode", "defensive")
    ma_period = int(config.get("ma_period", 200))
    max_buys_day = int(config.get("max_buys_day", 0))
    max_buys_week = int(config.get("max_buys_week", 0))
    force_buy_days = int(config.get("force_buy_days", 0))
    
    start_date = datetime.strptime(str(start_date_str).split()[0], "%Y-%m-%d")
    end_date = datetime.strptime(str(end_date_str).split()[0], "%Y-%m-%d")

    # 2. Ticker Resolution
    base_ticker_resolved = resolve_ticker(base_ticker)
    add_tickers_raw = [t.strip() for t in add_tickers_str.split(',') if t.strip()]
    add_tickers = [resolve_ticker(t) for t in add_tickers_raw]
    
    full_tickers_list = [base_ticker_resolved] + add_tickers
    
    # 3. Parse Steps
    steps = []
    
    if isinstance(steps_input, list):
        # Already a list of dicts (from Lab)
        # Ensure regex/resolving is done if needed, or assume pre-resolved?
        # Let's run resolver on tickers just in case
        for s in steps_input:
            s_copy = s.copy()
            s_copy['ticker'] = resolve_ticker(str(s['ticker']))
            steps.append(s_copy)
            
    elif isinstance(steps_input, pd.DataFrame):
        # From UI DataFrame
        steps_df = steps_input
        for index, row in steps_df.iterrows():
            try:
                raw_ticker = str(row["Ticker"])
                resolved_step_ticker = resolve_ticker(raw_ticker)
                
                steps.append({
                    "drop_pct": float(row["Drop(%)"]),
                    "shift_pct": float(row["Shift(%)"]),
                    "ticker": resolved_step_ticker,
                    "profit_pct": float(row["Profit(%)"])
                })
            except ValueError:
                st.error(f"Invalid data in row {index}")
                return None, None, None, None
    else:
        st.error("Invalid steps input format.")
        return None, None, None, None

    # 4. Fetch Data
    with st.spinner("Fetching Market Data..."):
        # Calculate buffer for 52-week high
        fetch_start = start_date - timedelta(days=365)
        df = fetch_and_process_data(full_tickers_list, fetch_start.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        
        if df.empty:
            st.error("No data returned. Check tickers or date range.")
            return None, None, None, None
            
        # Calc Peak (52-week high logic)
        high_col = f'High_{base_ticker_resolved}'
        peak_col = f'Peak_{base_ticker_resolved}'
        
        if high_col in df.columns:
            df[peak_col] = df[high_col].rolling(window=252, min_periods=1).max()
        else:
            st.error(f"High price data for {base_ticker_resolved} missing.")
            return None, None, None, None
            
        # Slice back to user start date
        df_sliced = df[df.index >= pd.Timestamp(start_date)]
        
        if df_sliced.empty:
            st.error("Data empty after slicing.")
            return None, None, None, None
            
    # 5. Run Backtest
    with st.spinner("Running Simulation..."):
        # Force reload to ensure latest Backtester logic is used (fix for caching issue)
        import importlib
        import backtest_engine
        importlib.reload(backtest_engine)
        from backtest_engine import Backtester
        
        backtester = Backtester(
            df_sliced, 
            initial_capital, 
            base_ticker_resolved, 
            add_tickers, 
            steps, 
            start_date=start_date, 
            end_date=end_date,
            sell_mode=sell_mode,
            cash_buffer_pct=cash_buffer_pct,
            use_ma_filter=use_ma,
            ma_mode=ma_mode,
            ma_period=ma_period,
            max_buys_day=max_buys_day,
            max_buys_week=max_buys_week,
            force_buy_days=force_buy_days
        )
        results = backtester.run()
        summary = backtester.get_summary()
        annual_stats = backtester.get_annual_stats()
        
    return results, summary, annual_stats, backtester
