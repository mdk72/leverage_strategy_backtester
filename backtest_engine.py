import pandas as pd
import numpy as np
from collections import defaultdict

class Backtester:
    def __init__(self, df, initial_capital, base_ticker, add_tickers, steps, start_date=None, end_date=None, sell_mode='limit', cash_buffer_pct=0, use_ma_filter=False, ma_period=200, ma_mode='defensive', max_buys_day=0, max_buys_week=0, force_buy_days=0):
        self.df = df.copy()
        self.initial_capital = initial_capital
        self.base_ticker = base_ticker
        self.add_tickers = add_tickers
        self.steps = sorted(steps, key=lambda x: abs(x['drop_pct']))
        self.sell_mode = sell_mode # 'limit' or 'close'
        
        # Trend Filter
        self.use_ma_filter = use_ma_filter
        self.ma_period = ma_period
        self.ma_period = ma_period
        self.ma_mode = ma_mode # 'defensive' (liquidate) or 'pause' (stop buying)
        
        # Buy Limits (Cooldown)
        self.max_buys_day = max_buys_day
        self.max_buys_week = max_buys_week
        self.force_buy_days = force_buy_days
        self.buy_history = [] # List of timestamps when a switch buy occurred
        self.last_buy_date = pd.Timestamp(start_date) if start_date else df.index[0] # Track for idle trigger
        
        # Cash Buffer: 사용자가 설정한 비율만큼 현금 보유 (동적 비율 유지)
        self.cash_buffer_pct = cash_buffer_pct
        
        # 동적 현금 관리: 포트폴리오 성장에 따라 현금 비중 유지
        # 초기 자본 중 버퍼 비율만큼은 현금으로 보유
        self.cash = initial_capital * (cash_buffer_pct / 100.0)
        
        # 리벨런싱 추적
        self.rebalance_count = 0
        self.total_rebalanced = 0
        
        # Store user-defined dates for accurate CAGR
        self.start_date = pd.Timestamp(start_date) if start_date else df.index[0]
        self.end_date = pd.Timestamp(end_date) if end_date else df.index[-1]
        
        # Holdings
        self.holdings = {t: 0 for t in [base_ticker] + add_tickers}
        
        self.lots = [] 
        self.step_active_flags = [False] * len(steps)
        self.trade_log = []
        self.daily_stats = []
        
        # Stats
        # Stats
        # Structure: { step_idx: { 'DROP': {'count':0, 'profits':[], 'amts':[]}, 'FORCE': ... } }
        self.step_stats = defaultdict(lambda: {
            'DROP': {'count': 0, 'profits': [], 'amts': []},
            'FORCE': {'count': 0, 'profits': [], 'amts': []}
        })

    def check_buy_limits(self, current_date):
        """
        Returns True if buying is allowed based on frequency limits.
        """
        if self.max_buys_day == 0 and self.max_buys_week == 0:
            return True
            
        # 1. Daily Check
        if self.max_buys_day > 0:
            day_count = sum(1 for d in self.buy_history if d.date() == current_date.date())
            if day_count >= self.max_buys_day:
                return False

        # 2. Weekly Check (Rolling 7 days)
        if self.max_buys_week > 0:
            # Inclusive window [current-6 days, current]
            start_window = (current_date - pd.Timedelta(days=6)).date()
            current_dt = current_date.date()
            
            week_count = sum(1 for d in self.buy_history if start_window <= d.date() <= current_dt)
            if week_count >= self.max_buys_week:
                return False
                
        return True

    def run(self):
        # 0. Initial Buy (First Day)
        # We process day 0 as setup.
        first_date = self.df.index[0]
        # Check if Base columns exist
        col_base_close = f'Close_{self.base_ticker}'
        if col_base_close not in self.df.columns:
            # Fallback or Error?
            p0 = 0
            print(f"Error: {col_base_close} not found in data.")
        else:
            p0 = self.df.iloc[0][col_base_close]
            
        
        if p0 > 0:
            # 투자 가능 금액 = 초기 자본 - 현금 버퍼
            investable = self.initial_capital - self.cash
            shares = investable / p0
            cost = shares * p0
            self.holdings[self.base_ticker] = shares
            
            buffer_note = f" ({self.cash_buffer_pct}% cash buffer: ${self.cash:,.0f})" if self.cash_buffer_pct > 0 else ""
            self.trade_log.append({
                "Date": first_date,
                "Action": "BUY (Init)",
                "Ticker": self.base_ticker,
                "Shares": shares,
                "Price": p0,
                "Value": cost,
                "Reason": f"Initial Entry{buffer_note}"
            })
            # Track Peak
            peak_price = self.df.iloc[0].get(f'High_{self.base_ticker}', p0)
            
            # Buy & Hold Init
            self.bh_shares = self.initial_capital / p0 if p0 > 0 else 0
        else:
            peak_price = 1.0 # arbitrary to avoid div by zero if data missing
            self.bh_shares = 0

        # MA Calculation
        ma_col = f'MA_{self.ma_period}'
        if self.use_ma_filter:
            # Calculate simple moving average on Base Ticker Close
            self.df[ma_col] = self.df[f'Close_{self.base_ticker}'].rolling(window=self.ma_period).mean()

        active_defensive = False # Fully out of market (Liquidated)
        is_ma_paused = False # Only pause buying (Hold existing)

        for date, row in self.df.iterrows():
            # Construct a helper to get price easily
            prices = {}
            for col in self.df.columns:
                if col.startswith("Close_"):
                    t = col.split("_")[1]
                    prices[t] = row[col]
            
            base_price = prices.get(self.base_ticker, 0)
            base_high = row.get(f'High_{self.base_ticker}', base_price)
            
            # --- MA Filter Logic ---
            ma_val = row.get(ma_col, 0) if self.use_ma_filter else 0
            
            # Check Regime Change
            if self.use_ma_filter and ma_val > 0:
                if base_price < ma_val:
                    # BEAR Market
                    if self.ma_mode == 'defensive':
                        # Mode 1: Liquidate All
                        if not active_defensive:
                            active_defensive = True
                            # Liquidate Everything
                            liquidation_value = 0
                            for t, s in self.holdings.items():
                                if s > 0:
                                    p = prices.get(t, 0)
                                    val = s * p
                                    self.cash += val
                                    self.holdings[t] = 0
                                    liquidation_value += val
                                    
                                    self.trade_log.append({
                                        "Date": date, "Action": "SELL (Defensive)", "Ticker": t,
                                        "Shares": s, "Price": p, "Value": val,
                                        "Reason": f"Below {self.ma_period} MA (Price {base_price:.2f} < MA {ma_val:.2f})"
                                    })
                            
                            self.lots = [] # Clear tracking lots
                            self.step_active_flags = [False] * len(self.steps) # Reset steps
                    
                    elif self.ma_mode == 'pause':
                        # Mode 2: Pause Buying Only
                        if not is_ma_paused:
                             is_ma_paused = True
                             # Log status change if desired? Or just silent.
                             # Keeping silent to avoid log clutter, or one log entry.
                             pass
                        
                elif base_price > ma_val:
                    # BULL Market -> Resume
                    if self.ma_mode == 'defensive':
                        if active_defensive:
                            active_defensive = False
                            # Re-Initialize (Buy Initial Position)
                            t_buy = self.base_ticker
                            p_buy = prices.get(t_buy, 0)
                            if p_buy > 0:
                                investable = self.cash * (1 - self.cash_buffer_pct/100.0)
                                s_buy = investable / p_buy
                                c_buy = s_buy * p_buy
                                self.cash -= c_buy
                                self.holdings[t_buy] += s_buy
                                
                                self.trade_log.append({
                                    "Date": date, "Action": "BUY (Resume)", "Ticker": t_buy,
                                    "Shares": s_buy, "Price": p_buy, "Value": c_buy,
                                    "Reason": f"Reclaimed {self.ma_period} MA"
                                })
                    elif self.ma_mode == 'pause':
                        if is_ma_paused:
                            is_ma_paused = False

            
            # Skip trading if Defensive
            if active_defensive:
                # Still record stats
                port_value = self.cash
                self.daily_stats.append({
                    "Date": date,
                    "Open": row.get(f"Open_{self.base_ticker}", 0),
                    "High": base_high, 
                    "Low": row.get(f"Low_{self.base_ticker}", 0),
                    f"Price_{self.base_ticker}": base_price,
                    "Peak": peak_price, # This peak is for the base ticker, not portfolio
                    "Drawdown": 0, # In defensive mode, we are in cash, so no drawdown from peak equity
                    "PortfolioValue": port_value,
                    "BuyHoldValue": self.bh_shares * base_price,
                    "Cash": self.cash,
                    "MA_Line": ma_val
                })
                continue # Skip the rest of loop

            # 1. Update Drawdown (Using Pre-calculated 52-Week Peak)
            # main.py adds 'Peak_{base}' column
            peak_col = f'Peak_{self.base_ticker}'
            peak_price = row.get(peak_col, base_price)
            
            # Fallback if 0
            if peak_price <= 0: peak_price = base_price
            
            drawdown_pct = 0.0
            if peak_price > 0:
                drawdown_pct = (peak_price - base_price) / peak_price * 100
            
            # 2. Update Portfolio Value (includes cash + stock holdings)
            port_value = self.cash
            for t, s in self.holdings.items():
                if t in prices:
                    port_value += s * prices[t]
            
            # 3. Check Exits (Profit Taking on Leveraged Lots)
            lots_to_remove = []
            for i, lot in enumerate(self.lots):
                ticker = lot['ticker']
                curr_p = prices.get(ticker, 0) # Close Price
                if curr_p == 0: continue
                
                # Limit Sell Logic Data
                high_p = row.get(f'High_{ticker}', curr_p)
                open_p = row.get(f'Open_{ticker}', curr_p)
                
                step_idx = lot['step_idx']
                target_pct = self.steps[step_idx]['profit_pct']
                profit_target = lot['price'] * (1 + target_pct / 100.0) # Calculate target price
                
                executed = False
                exec_price = 0
                
                # Sell Mode Check
                if self.sell_mode == 'limit':
                    # 1. Gap Up: Open > Target -> Sell at Open
                    if open_p >= profit_target:
                        exec_price = open_p
                        executed = True
                    # 2. Intraday Hit: High >= Target -> Sell at Target
                    elif high_p >= profit_target:
                        exec_price = profit_target
                        executed = True
                else: # 'close' mode
                    # Classic logic: if Close Profit >= Target, sell at Close
                    # Calculate close-based profit
                    profit_at_close = (curr_p - lot['price']) / lot['price'] * 100
                    if profit_at_close >= target_pct:
                        exec_price = curr_p
                        executed = True
                
                if executed:
                    # Sell Lot
                    profit = (exec_price - lot['price']) / lot['price'] * 100
                    rev = lot['shares'] * exec_price
                    cost_basis = lot['shares'] * lot['price']
                    profit_amt = rev - cost_basis
                    
                    self.cash += rev
                    self.holdings[lot['ticker']] -= lot['shares']
                    
                    # Record Per-Step Profit
                    # Record Per-Step Profit
                    entry_type = lot.get('entry_type', 'DROP') # Default to DROP for compatibility
                    self.step_stats[step_idx][entry_type]['profits'].append(profit)
                    self.step_stats[step_idx][entry_type]['amts'].append(profit_amt)
                    
                    # 동적 리벨런싱: 현금 비중을 목표 %로 유지
                    rebalance_note = ""
                    if self.cash_buffer_pct > 0:
                        # Recalculate current total equity
                        curr_equity = self.cash
                        for t_h, s_h in self.holdings.items():
                            curr_equity += s_h * prices.get(t_h, 0)
                            
                        target_cash = curr_equity * (self.cash_buffer_pct / 100.0)
                        excess_cash = self.cash - target_cash
                        
                        if excess_cash > target_cash * 0.1: # Threshold for rebalancing
                            # Buy Base Ticker with excess cash
                            t_base = self.base_ticker
                            p_base = prices.get(t_base, 0)
                            if p_base > 0:
                                amt_invest = excess_cash
                                shares_add = amt_invest / p_base
                                self.cash -= amt_invest
                                self.holdings[t_base] += shares_add
                                self.rebalance_count += 1
                                self.total_rebalanced += amt_invest
                                rebalance_note = " (Rebalanced)"
                    else:
                        # 현금 버퍼 없으면 전액 재투자 (Compounding)
                        # Reinvest all cash into Base Ticker
                        t_base = self.base_ticker
                        p_base = prices.get(t_base, 0)
                        if p_base > 0 and self.cash > 0:
                            shares_base = self.cash / p_base
                            cost = shares_base * p_base
                            self.holdings[t_base] = self.holdings.get(t_base, 0) + shares_base
                            self.cash -= cost
                            rebalance_note = " (Reinvested)"
                    
                    self.trade_log.append({
                        "Date": date,
                        "Action": f"SELL (Profit/{entry_type})", # Distinguished Action
                        "Ticker": lot['ticker'],
                        "Shares": lot['shares'],
                        "Price": exec_price,
                        "Value": rev,
                        "Reason": f"Hit Target {target_pct}% (Profit {profit:.1f}%){rebalance_note}",
                        "StepIdx": step_idx,
                        "DropPct": self.steps[step_idx]['drop_pct'],
                        "ProfitAmt": profit_amt,
                        "ProfitPct": profit,
                        "BuyDate": lot.get('buy_date'),
                        "DaysHeld": (date - lot.get('buy_date')).days
                    })
                    
                    self.step_active_flags[step_idx] = False
                    lots_to_remove.append(i)
            
            for i in sorted(lots_to_remove, reverse=True):
                del self.lots[i]

            # 4. Check Entries (Switching on Drawdown)
            # Only check entries if logic is NOT paused by MA filter
            # 4. Check Entries (Switching on Drawdown)
            # Only check entries if logic is NOT paused by MA filter
            if not is_ma_paused:
                
                # --- Forced Buy Logic (Idle Trigger) ---
                forced_buy_executed = False
                if self.force_buy_days > 0:
                    days_idle = (date - self.last_buy_date).days
                    if days_idle >= self.force_buy_days:
                        # Find first inactive step
                        target_step_idx = -1
                        for i, flag in enumerate(self.step_active_flags):
                            if not flag:
                                target_step_idx = i
                                break
                        
                        if target_step_idx != -1:
                            # Execute Forced Buy
                            step = self.steps[target_step_idx]
                            shift_val = port_value * (step['shift_pct'] / 100.0)
                            base_val_held = self.holdings.get(self.base_ticker, 0) * base_price
                            
                            # Sufficient Base?
                            if base_val_held >= shift_val * 0.9:
                                # Execute Switch
                                shares_to_sell = shift_val / base_price
                                self.holdings[self.base_ticker] -= shares_to_sell
                                self.cash += shift_val
                                
                                buy_ticker = step['ticker']
                                buy_price = prices.get(buy_ticker, 0)
                                if buy_price > 0:
                                    shares_to_buy = shift_val / buy_price
                                    cost = shares_to_buy * buy_price
                                    self.holdings[buy_ticker] = self.holdings.get(buy_ticker, 0) + shares_to_buy
                                    self.cash -= cost
                                    
                                    self.lots.append({
                                        'ticker': buy_ticker,
                                        'shares': shares_to_buy,
                                        'price': buy_price,
                                        'step_idx': target_step_idx,
                                        'cost': cost,
                                        'buy_date': date,
                                        'entry_type': 'FORCE'
                                    })
                                    self.step_active_flags[target_step_idx] = True
                                    self.last_buy_date = date # Reset Idle Timer
                                    self.buy_history.append(date) # Count towards limits? Maybe force override? 
                                    # Let's count it to prevent Double Buy same day
                                    
                                    self.trade_log.append({
                                        "Date": date,
                                        "Action": "FORCE (Idle)",
                                        "Ticker": f"{self.base_ticker}->{buy_ticker}",
                                        "Shares": shares_to_buy,
                                        "Price": buy_price,
                                        "Value": shift_val,
                                        "Reason": f"Idle {days_idle} days >= {self.force_buy_days}",
                                        "StepIdx": target_step_idx,
                                        "DropPct": 0 # Ignore drop
                                    })
                                    
                                    # Record Stat
                                    self.step_stats[target_step_idx]['FORCE']['count'] += 1
                                    
                                    forced_buy_executed = True

                # Standard Drop Logic (Skip if Forced Buy happened today)
                if not forced_buy_executed:
                    for i, step in enumerate(self.steps):
                        # Condition: Drawdown Magnitude >= Trigger Magnitude AND Step Not Active
                        # Use abs() to handle negative input (e.g. -5%) vs positive drawdown (5%)
                        if drawdown_pct >= abs(step['drop_pct']) and not self.step_active_flags[i]:
                            # Shift
                            shift_val = port_value * (step['shift_pct'] / 100.0)
                            base_val_held = self.holdings.get(self.base_ticker, 0) * base_price
                            
                            if base_val_held < shift_val * 0.9: 
                                continue
                            
                            # Check Time-based Buy Limits
                            if not self.check_buy_limits(date):
                                self.trade_log.append({
                                    "Date": date,
                                    "Action": "SKIP (Limit)",
                                    "Ticker": step['ticker'],
                                    "Shares": 0,
                                    "Price": 0,
                                    "Value": 0,
                                    "Reason": "Max Buys Limit Reached",
                                    "StepIdx": i,
                                    "DropPct": step['drop_pct']
                                })
                                continue
                            
                            # Record Buy Count
                            
                            # Record Buy Count
                            self.step_stats[i]['DROP']['count'] += 1
                            
                            # Sell Base
                            shares_to_sell = shift_val / base_price
                            self.holdings[self.base_ticker] -= shares_to_sell
                            self.cash += shift_val
                            
                            # Buy Leveraged
                            buy_ticker = step['ticker']
                            buy_price = prices.get(buy_ticker, 0)
                            if buy_price > 0:
                                shares_to_buy = shift_val / buy_price
                                cost = shares_to_buy * buy_price
                                self.holdings[buy_ticker] = self.holdings.get(buy_ticker, 0) + shares_to_buy
                                self.cash -= cost
                                
                                self.lots.append({
                                    'ticker': buy_ticker,
                                    'shares': shares_to_buy,
                                    'price': buy_price,
                                    'step_idx': i,
                                    'cost': cost,
                                    'buy_date': date,
                                    'entry_type': 'DROP'
                                })
                                self.step_active_flags[i] = True
                                
                                self.trade_log.append({
                                    "Date": date,
                                    "Action": "SWITCH",
                                    "Ticker": f"{self.base_ticker}->{buy_ticker}",
                                    "Shares": shares_to_buy,
                                    "Price": buy_price,
                                    "Value": shift_val,
                                    "Reason": f"Drawdown {drawdown_pct:.2f}% >= {step['drop_pct']}%",
                                    "StepIdx": i,
                                "DropPct": step['drop_pct']
                            })
                            
                            self.buy_history.append(date)
                            self.last_buy_date = date # Update for Idle Timer

            # Buy & Hold Value
            bh_val = 0.0
            if self.bh_shares > 0:
                bh_val = self.bh_shares * base_price
            
            # Record Stats (Ordered)
            stats = {
                "Date": date,
                "Open": row.get(f"Open_{self.base_ticker}", 0),
                "High": base_high, 
                "Low": row.get(f"Low_{self.base_ticker}", 0),
                f"Price_{self.base_ticker}": base_price, # Renamed for plotting
                "Peak": peak_price,
                "Drawdown": drawdown_pct,
                "PortfolioValue": port_value,
                "BuyHoldValue": bh_val,
                "Cash": self.cash  # 현금 (동적 비율 유지)
            }
            
            # Fixed Order: Base -> Tickers in Input Order
            ordered_tickers = [self.base_ticker] + self.add_tickers
            
            for t in ordered_tickers:
                shares = self.holdings.get(t, 0)
                p = prices.get(t, 0)
                val = shares * p
                pct = (val / port_value * 100) if port_value > 0 else 0
                
                # Suffix for clarity
                stats[f"{t}_Price"] = p
                stats[f"{t}_Hold"] = shares
                stats[f"{t}_Val"] = val
                stats[f"{t}_Pct"] = pct
                
            self.daily_stats.append(stats)
            
        # --- END OF LOOP ---
        # 5. Log Current Holdings (Unsold)
        last_date = self.df.index[-1]
        last_row = self.df.iloc[-1]
        
        # Get final prices
        final_prices = {}
        for col in self.df.columns:
            if col.startswith("Close_"):
                t = col.split("_")[1]
                final_prices[t] = last_row[col]
        
        for lot in self.lots:
            curr_p = final_prices.get(lot['ticker'], 0)
            if curr_p > 0:
                profit_unrealized = (curr_p - lot['price']) / lot['price'] * 100
                val = lot['shares'] * curr_p
                days = (last_date - lot['buy_date']).days
                
                self.trade_log.append({
                    "Date": last_date,
                    "Action": "HOLDING",
                    "Ticker": lot['ticker'],
                    "Shares": lot['shares'],
                    "Price": curr_p,
                    "Value": val,
                    "Reason": "Open Position",
                    "StepIdx": lot['step_idx'],
                    "DropPct": self.steps[lot['step_idx']]['drop_pct'],
                    "ProfitAmt": val - lot['cost'],
                    "ProfitPct": profit_unrealized,
                    "BuyDate": lot['buy_date'],
                    "DaysHeld": days
                })

        # Create DataFrame with sorted columns
        df_stats = pd.DataFrame(self.daily_stats)
        if not df_stats.empty:
            # Reorder columns to put general stuff first, then ticker stuff
            # Reorder columns to put general stuff first, then ticker stuff
            # Reorder columns to put general stuff first, then ticker stuff
            cols = ["Date", "Open", "High", "Low", f"Price_{self.base_ticker}", "Peak", "Drawdown", "PortfolioValue", "BuyHoldValue", "Cash"]
            for t in ordered_tickers:
                cols.extend([f"{t}_Price", f"{t}_Hold", f"{t}_Val", f"{t}_Pct"])
            
            # Only use columns that actually exist
            existing_cols = [c for c in cols if c in df_stats.columns]
            df_stats = df_stats[existing_cols]
            df_stats.set_index("Date", inplace=True)
            return df_stats
        return df_stats
    
    def get_summary(self):
        final_val = self.daily_stats[-1]['PortfolioValue']
        total_ret = (final_val - self.initial_capital) / self.initial_capital * 100
        
        df = pd.DataFrame(self.daily_stats)
        peak = df['PortfolioValue'].cummax()
        mdd = ((df['PortfolioValue'] - peak) / peak * 100).min()
        
        # Build Step Stats String
        step_stats_str = ""
        for i, step in enumerate(self.steps):
            stats = self.step_stats.get(i, {'DROP':{'count':0,'profits':[]}, 'FORCE':{'count':0,'profits':[]}})
            d_count = stats['DROP']['count']
            f_count = stats['FORCE']['count']
            
            d_profits = stats['DROP']['profits']
            f_profits = stats['FORCE']['profits']
            
            d_avg = sum(d_profits)/len(d_profits) if d_profits else 0.0
            f_avg = sum(f_profits)/len(f_profits) if f_profits else 0.0
            
            step_stats_str += (
                f"\n[Step {i+1} | Drop {step['drop_pct']}%]\n"
                f"  - Buys: Drop({d_count}) / Force({f_count})\n"
                f"  - Avg Profit: Drop({d_avg:.2f}%) / Force({f_avg:.2f}%)\n"
            )

        # CAGR Calculation
        # Use user-defined dates if available to capture full holding period
        start_ts = self.start_date if hasattr(self, 'start_date') else df.index[0]
        end_ts = self.end_date if hasattr(self, 'end_date') else df.index[-1]
            
        # Add 1 day to be inclusive (e.g. Jan 1 to Jan 1 is 1 day, not 0)
        days = (end_ts - start_ts).days + 1
        years = days / 365.25
        
        if years > 0:
            cagr = (final_val / self.initial_capital) ** (1 / years) - 1
            cagr_pct = cagr * 100
        else:
            cagr_pct = 0.0

        # Buy & Hold Stats
        col_price = f"Price_{self.base_ticker}"
        if col_price in df.columns:
            prices = df[col_price]
            if not prices.empty and prices.iloc[0] > 0:
                bh_ret = (prices.iloc[-1] - prices.iloc[0]) / prices.iloc[0] * 100
                
                # BH CAGR
                bh_final_val = prices.iloc[-1] / prices.iloc[0] * self.initial_capital
                if years > 0:
                    bh_cagr = (bh_final_val / self.initial_capital) ** (1 / years) - 1
                    bh_cagr_pct = bh_cagr * 100
                else:
                    bh_cagr_pct = 0.0

                peak_bh = prices.cummax()
                dd_bh = ((prices - peak_bh) / peak_bh * 100).min()
            else:
                bh_ret = 0.0
                dd_bh = 0.0
                bh_cagr_pct = 0.0
        else:
            bh_ret = 0.0
            dd_bh = 0.0
            bh_cagr_pct = 0.0

        
        return {
            "Final Value": f"${final_val:,.2f}",
            "Total Return": f"{total_ret:.2f}%",
            "CAGR": f"{cagr_pct:.2f}%",
            "MDD": f"{mdd:.2f}%",
            "CAGR": f"{cagr_pct:.2f}%",
            "MDD": f"{mdd:.2f}%",
            "Trade Count": len([t for t in self.trade_log if t['Action'] not in ['SKIP (Limit)', 'HOLDING']]),
            "Cash Buffer": f"{self.cash_buffer_pct:.0f}%" if self.cash_buffer_pct > 0 else "None",
            "Final Cash": f"${df['Cash'].iloc[-1]:,.2f}" if not df.empty and 'Cash' in df.columns else "$0",
            "Rebalance Count": self.rebalance_count if self.cash_buffer_pct > 0 else 0,
            "Total Rebalanced": f"${self.total_rebalanced:,.2f}" if self.cash_buffer_pct > 0 else "$0",
            "BH Return": f"{bh_ret:.2f}%",
            "BH CAGR": f"{bh_cagr_pct:.2f}%",
            "BH MDD": f"{dd_bh:.2f}%",
            "Step Stats": step_stats_str
        }

    def get_annual_stats(self):
        """
        Calculates Annual Returns, MDD, and Trade Counts for Strategy and Buy & Hold.
        and a Total column.
        """
        df = pd.DataFrame(self.daily_stats)
        if df.empty:
            return pd.DataFrame()

        # Fix: Ensure 'Date' column is used as datetime index
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)

        years = df.index.year.unique().sort_values()
        
        if years.empty:
             return pd.DataFrame()
             
        start_year = years[0]
        end_year = years[-1]
        
        # Helper for MDD
        def calc_mdd(series):
            if series.empty: return 0.0
            peak = series.cummax()
            dd = (series - peak) / peak * 100
            return dd.min()
            
        # Helper for Return
        def calc_ret(start_val, end_val):
            if start_val == 0: return 0.0
            return (end_val - start_val) / start_val * 100

        # Total Period Stats
        total_start_val = self.initial_capital
        total_end_val = df['PortfolioValue'].iloc[-1]
        total_strat_ret = calc_ret(total_start_val, total_end_val)
        total_strat_mdd = calc_mdd(df['PortfolioValue'])
        total_trades = len([t for t in self.trade_log if t['Action'] not in ['SKIP (Limit)', 'HOLDING']])

        # BH Total
        col_price = f"Price_{self.base_ticker}"
        if col_price in df.columns:
            bh_series = df[col_price]
            total_bh_ret = calc_ret(bh_series.iloc[0], bh_series.iloc[-1])
            total_bh_mdd = calc_mdd(bh_series)
        else:
            total_bh_ret = 0.0
            total_bh_mdd = 0.0
            bh_series = pd.Series()
        
        # Calculate Total CAGR
        start_ts = df.index[0]
        end_ts = df.index[-1]
        t_days = (end_ts - start_ts).days + 1
        t_years = t_days / 365.25
        
        total_strat_cagr = 0.0
        if total_start_val > 0 and t_years > 0:
            total_strat_cagr = (total_end_val / total_start_val) ** (1 / t_years) - 1
            total_strat_cagr *= 100
            
        total_bh_cagr = 0.0
        # If BH series exists
        if not bh_series.empty:
            bh_start_val = bh_series.iloc[0]
            bh_end_val = bh_series.iloc[-1]
            if bh_start_val > 0 and t_years > 0:
                total_bh_cagr = (bh_end_val / bh_start_val) ** (1 / t_years) - 1
                total_bh_cagr *= 100

        results = {
            "Metrics": ["Return (Strategy)", "Return (Buy&Hold)", "MDD (Strategy)", "MDD (Buy&Hold)", "Trades (Strategy)"]
        }
        
        # Iterate Years
        for y in years:
            y_df = df[df.index.year == y]
            if y_df.empty: continue
            
            # ... (Existing yearly calcs) ...
            # Reuse existing variables (re-calculating for clarity/safety inside loop if needed, 
            # but usually we need to grab them from where they were calculated in the original code? 
            # Wait, I am replacing the loop logic basically or I need to insert the CAGR row value)
            
            # Since I am replacing the block from defining 'results' down to 'return', 
            # I must reconstruct the loop carefully.
            
            y_end_val = y_df['PortfolioValue'].iloc[-1]
            
            prev_year_mask = df.index.year == (y - 1)
            if prev_year_mask.any():
                y_start_val = df.loc[prev_year_mask, 'PortfolioValue'].iloc[-1]
            else:
                y_start_val = self.initial_capital

            y_strat_ret = calc_ret(y_start_val, y_end_val)
            y_strat_mdd = calc_mdd(y_df['PortfolioValue'])
            
            y_trades = sum(1 for t in self.trade_log 
                           if pd.Timestamp(t['Date']).year == y 
                           and t['Action'] not in ['SKIP (Limit)', 'HOLDING'])
            
            if not bh_series.empty:
                y_bh_series = bh_series[bh_series.index.year == y]
                y_bh_end = y_bh_series.iloc[-1]
                if prev_year_mask.any():
                     y_bh_start = df.loc[prev_year_mask, col_price].iloc[-1]
                else:
                     y_bh_start = y_bh_series.iloc[0]
                     
                y_bh_ret = calc_ret(y_bh_start, y_bh_end)
                y_bh_mdd = calc_mdd(y_bh_series)
            else:
                y_bh_ret = 0.0
                y_bh_mdd = 0.0

            results[str(y)] = [
                f"{y_strat_ret:.2f}%",
                f"{y_bh_ret:.2f}%",
                f"{y_strat_mdd:.2f}%",
                f"{y_bh_mdd:.2f}%",
                str(y_trades)
            ]
            
        # Add Total Column
        total_col_name = f"{start_year}~{end_year}" if start_year != end_year else str(start_year) + " (Total)"
        if start_year == end_year: total_col_name = "Total"

        # Merge CAGR into Total Return cell
        # Format: "Return% (CAGR%)"
        str_ret_cagr = f"{total_strat_ret:.2f}% ({total_strat_cagr:.2f}%)"
        bh_ret_cagr = f"{total_bh_ret:.2f}% ({total_bh_cagr:.2f}%)"

        results[total_col_name] = [
            str_ret_cagr,
            bh_ret_cagr,
            f"{total_strat_mdd:.2f}%",
            f"{total_bh_mdd:.2f}%",
            str(total_trades)
        ]
        
        return pd.DataFrame(results)

    def get_step_metrics_df(self):
        """
        Returns a DataFrame with detailed statistics for each step.
        """
        rows = []
        # Calculate total profit across all steps for contribution logic
        # Need to sum amounts from both DROP and FORCE
        total_strategy_profit = 0
        for s_stat in self.step_stats.values():
            total_strategy_profit += sum(s_stat['DROP']['amts']) + sum(s_stat['FORCE']['amts'])
        
        for i, step in enumerate(self.steps):
            stats = self.step_stats.get(i, {'DROP':{'count':0,'profits':[],'amts':[]}, 'FORCE':{'count':0,'profits':[],'amts':[]}})
            
            d_count = stats['DROP']['count']
            f_count = stats['FORCE']['count']
            
            d_profits = stats['DROP']['profits']
            f_profits = stats['FORCE']['profits']
            
            d_amts = stats['DROP']['amts']
            f_amts = stats['FORCE']['amts']
            
            d_avg = sum(d_profits)/len(d_profits) if d_profits else 0.0
            f_avg = sum(f_profits)/len(f_profits) if f_profits else 0.0
            
            # Absolute Profit Contribution
            step_total_profit_amt = sum(d_amts) + sum(f_amts)
            
            contribution_pct = 0.0
            if total_strategy_profit > 0:
                contribution_pct = (step_total_profit_amt / total_strategy_profit) * 100
            
            # Formatting
            buy_count_str = f"{d_count} / {f_count}"
            avg_prof_str = f"{d_avg:.2f}% / {f_avg:.2f}%"
            
            rows.append({
                "Step": f"Step {i+1}",
                "Drop Condition": f"{step['drop_pct']}%",
                "Buy Ratio": f"{step['shift_pct']}%",
                "Target Profit": f"{step['profit_pct']}%",
                "Buy Count (Drop/Force)": buy_count_str,
                "Avg Profit (Drop/Force)": avg_prof_str,
                "Total Profit ($)": f"${step_total_profit_amt:,.0f}",
                "Contribution": f"{contribution_pct:.1f}%"
            })
            
        return pd.DataFrame(rows)
