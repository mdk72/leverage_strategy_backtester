import os
import json
import pandas as pd
from datetime import datetime
import streamlit as st

# --- Constants ---
CSV_FILE = "steps_config.csv"
CONFIG_FILE = "config.json"
HISTORY_FILE = "simulation_history.csv"

# --- Config Persistence ---
def load_config():
    """Load settings from config.json"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    # Defaults
    return {
        "base_ticker": "QQQ",
        "add_tickers": "TQQQ",
        "initial_capital": 10000,
        "start_date": "2025-01-01",
        "end_date": datetime.today().strftime("%Y-%m-%d"),
        "sell_mode": "limit",
        "cash_buffer_pct": 0
    }

def save_config(config):
    """Save settings to config.json"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

# --- Steps Data Persistence ---
def load_steps_data():
    if os.path.exists(CSV_FILE):
        try:
            return pd.read_csv(CSV_FILE)
        except Exception as e:
            st.error(f"Error loading config: {e}")
    
    # Default Data
    return pd.DataFrame([
        [-5.0, 10.0, "SSO", 5.0],
        [-10.0, 20.0, "SSO", 5.0],
        [-15.0, 30.0, "SSO", 5.0],
        [-20.0, 40.0, "UPRO", 10.0],
        [-25.0, 50.0, "UPRO", 10.0],
        [-30.0, 50.0, "UPRO", 10.0],
        [-50.0, 50.0, "UPRO", 10.0],
    ], columns=["Drop(%)", "Shift(%)", "Ticker", "Profit(%)"])

def save_steps_data(df):
    df.to_csv(CSV_FILE, index=False)

# --- History Persistence ---
def log_simulation_history(params, results_summary):
    """Append simulation run to history CSV, avoiding duplicates"""
    record = {
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **params,
        **results_summary
    }
    
    df_new = pd.DataFrame([record])
    
    if os.path.exists(HISTORY_FILE):
        try:
            df_hist = pd.read_csv(HISTORY_FILE)
            
            # Check for duplicates
            # We must compare all columns present in the NEW record.
            # If the old history lacks a column (e.g. 'ForceBuyDays'), we treat it as missing/different.
            
            # Align df_hist schema to df_new for comparison
            for col in df_new.columns:
                if col not in df_hist.columns and col != "Timestamp":
                    # If history doesn't have this param, assume it was 0 or Default for previous runs
                    # limiting mostly to numeric 0 or False or Empty String based on type? 
                    # Safer to assume 'NaN' or specific default. 
                    # But string comparison handles different types poorly.
                    # Let's fill with a sentinel that won't match 30.
                    df_hist[col] = None 

            cols_to_check = [c for c in df_new.columns if c != "Timestamp"]
            
            # Perform comparison
            # We iterate column by column to handle types gracefully (e.g., 30 vs 30.0)
            is_duplicate = False
            candidates = pd.Series([True] * len(df_hist), index=df_hist.index)

            for col in cols_to_check:
                val = df_new[col].iloc[0]
                hist_col = df_hist[col]

                # Use numeric equality if possible to handle int vs float (30 vs 30.0)
                if pd.api.types.is_numeric_dtype(hist_col) and isinstance(val, (int, float)):
                    # Compare numeric values (ignoring small float diffs if needed, but == usually fine for params)
                    candidates &= (hist_col == val)
                else:
                    # String fallback for non-numeric columns
                    candidates &= (hist_col.astype(str) == str(val))
                
                if not candidates.any():
                    break
            
            if candidates.any():
                is_duplicate = True
            
            if is_duplicate:
                # Duplicate found, skip
                return

            df_hist = pd.concat([df_hist, df_new], ignore_index=True)
        except Exception as e:
             # Fallback if read duplicate fails
             df_hist = df_new
    else:
        df_hist = df_new
    
    df_hist.to_csv(HISTORY_FILE, index=False)
