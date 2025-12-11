import yfinance as yf
import pandas as pd

def fetch_and_process_data(tickers, start_date, end_date=None):
    """
    Fetches data for multiple tickers and aligns them.
    Args:
        tickers (list): List of ticker strings (e.g. ['SPY', 'SSO', 'UPRO'])
        start_date (str): YYYY-MM-DD
        end_date (str): YYYY-MM-DD or None
    Returns:
        pd.DataFrame: Columns = [Close_SPY, Close_SSO, ... High_SPY...]
    """
    if isinstance(tickers, str):
        tickers = [tickers]
        
    print(f"INFO: Fetching data for: {tickers}")
    try:
        # Fetch Data
        df = yf.download(tickers, start=start_date, end=end_date, progress=False)
    except Exception as e:
        raise Exception(f"Download invalid: {e}")

    if df.empty:
        return pd.DataFrame()

    # Handle Multi-Ticker vs Single Ticker Structure
    if len(tickers) > 1:
        # Structure is MultiIndex: (Price, Ticker)
        # We need to flatten this.
        
        try:
            # We want Open, High, Low, Close
            # df.columns levels are [Price, Ticker] usually.
            
            # Helper to extract and rename
            def get_flattened(price_col):
                # price_col is 'Open', 'High', 'Low', 'Close' or 'Adj Close'
                if price_col not in df.columns.levels[0]:
                    if price_col == 'Close' and 'Adj Close' in df.columns.levels[0]:
                        target = df['Adj Close']
                    else:
                        return pd.DataFrame() # Missing
                else:
                    target = df[price_col]
                    
                target.columns = [f"{price_col}_{t}" for t in target.columns]
                return target

            df_open = get_flattened('Open')
            df_high = get_flattened('High')
            df_low = get_flattened('Low')
            # Prefer Close, fallback Adj Close
            if 'Close' in df.columns.levels[0]:
                df_close = get_flattened('Close')
            else:
                 # Manually handle Adj Close naming to Close_
                 target = df['Adj Close']
                 target.columns = [f"Close_{t}" for t in target.columns]
                 df_close = target
            
            # Merge all
            result = pd.concat([df_open, df_high, df_low, df_close], axis=1)
            
        except KeyError as e:
            # Fallback for unexpected structure
            print(f"KeyError in data structure: {e}")
            return pd.DataFrame()
            
    else:
        # Single Ticker
        t = tickers[0]
        result = pd.DataFrame()
        result[f'Open_{t}'] = df['Open']
        result[f'High_{t}'] = df['High']
        result[f'Low_{t}'] = df['Low']
        result[f'Close_{t}'] = df['Close']

    # Handle Missing
    # Forward fill first, then drop initial NaNs
    result.ffill(inplace=True)
    result.dropna(inplace=True)
    
    return result

if __name__ == "__main__":
    # Test
    try:
        d = fetch_and_process_data(["SPY", "SSO"], "2023-01-01")
        print(d.head())
    except Exception as e:
        print(e)
