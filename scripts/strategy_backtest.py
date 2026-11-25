"""Backtest the strategies that trading bots and AI agents on major platforms run.

Runs on GitHub Actions (needs internet): downloads daily, dividend-adjusted prices with
yfinance, simulates each strategy with simple trading costs and writes ONLY aggregated
statistics to data/strategy_backtest.json (no raw prices are published).

Usage: python scripts/strategy_backtest.py [--synthetic]   (--synthetic = offline self-test)
"""
import json, math, os, sys
from datetime import date

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "strategy_backtest.json")
START = "2015-06-01"          # extra months so 200-day / 12-month signals are ready by 2016
EVAL_START = "2016-01-04"
TICKERS = ["SPY", "QQQ", "EFA", "AGG", "GLD", "BIL", "^VIX"]
COST = 0.0005                 # 0.05% per unit of turnover (commission + slippage)


def load_prices(synthetic=False):
    if synthetic:
        rng = np.random.default_rng(7)
        idx = pd.bdate_range(START, date.today())
        out = {}
        for t, mu, sd in [("SPY", .10, .18), ("QQQ", .14, .24), ("EFA", .06, .17), ("AGG", .02, .05),
                          ("GLD", .06, .15), ("BIL", .02, .005)]:
            r = rng.normal(mu / 252, sd / math.sqrt(252), len(idx))
            out[t] = 100 * np.exp(np.cumsum(r))
        df = pd.DataFrame(out, index=idx)
        df["^VIX"] = 15 + 10 * np.abs(np.sin(np.arange(len(idx)) / 90)) + rng.normal(0, 2, len(idx)).clip(-5, 20)
        return df
    import yfinance as yf
    raw = yf.download(TICKERS, start=START, auto_adjust=True, progress=False)["Close"]
    return raw.dropna(how="any")


def rsi(series, n):
    d = series.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def run_weights(px, w):
    """Daily portfolio from target weights decided at close t, held over t+1 (no look-ahead)."""
    rets = px.pct_change().fillna(0)
    w = w.reindex(px.index).ffill().fillna(0)
    held = w.shift(1).fillna(0)
    gross = (held * rets[held.columns]).sum(axis=1)
    turnover = (w - w.shift(1).fillna(0)).abs().sum(axis=1)
    net = gross - turnover.shift(1).fillna(0) * COST
    return net, turnover


def stats(daily, cash, invested=None, turnover=None, name=""):
    daily = daily[daily.index >= EVAL_START]
    cash = cash[cash.index >= EVAL_START]
    eq = (1 + daily).cumprod()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()
    vol = daily.std() * math.sqrt(252)
    excess = daily - cash
    sharpe = excess.mean() / daily.std() * math.sqrt(252) if daily.std() > 0 else 0
    yearly = (1 + daily).groupby(daily.index.year).prod() - 1
    y2020 = yearly.get(2020, np.nan)
    y2022 = yearly.get(2022, np.nan)
    out = {
        "cagr_pct": round(cagr * 100, 1),
        "max_drawdown_pct": round(dd * 100, 1),
        "volatility_pct": round(vol * 100, 1),
        "sharpe": round(sharpe, 2),
        "worst_year_pct": round(yearly.min() * 100, 1),
        "worst_year": int(yearly.idxmin()),
        "best_year_pct": round(yearly.max() * 100, 1),
        "y2020_pct": None if np.isnan(y2020) else round(y2020 * 100, 1),
        "y2022_pct": None if np.isnan(y2022) else round(y2022 * 100, 1),
        "final_10k": int(round(10000 * eq.iloc[-1], -1)),
        "positive_years": f"{int((yearly > 0).sum())}/{len(yearly)}",
    }
    if invested is not None:
        out["time_invested_pct"] = round(float(invested[invested.index >= EVAL_START].mean()) * 100)
    if turnover is not None:
        t = turnover[turnover.index >= EVAL_START]
        out["trades_per_year"] = round(float((t > 1e-9).sum()) / years, 1)
    return out


def bs_call(S, K, T, v):
    if T <= 0 or v <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + 0.5 * v * v * T) / (v * math.sqrt(T))
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return S * N(d1) - K * N(d1 - v * math.sqrt(T))


def options_weekly(px, kind):
    """Modelled weekly covered call / cash-secured put on SPY, ~1 sigma out of the money.
    Implied vol = VIX/100 at entry; premium haircut 5% for spreads; no early assignment."""
    spy, vix = px["SPY"], px["^VIX"]
    weeks = spy.resample("W-FRI").last().dropna()
    vixw = vix.resample("W-FRI").last().reindex(weeks.index).ffill()
    cashw = px["BIL"].resample("W-FRI").last().reindex(weeks.index).ffill()
    rets, dates = [], []
    for i in range(1, len(weeks)):
        S0, S1 = weeks.iloc[i - 1], weeks.iloc[i]
        v = float(vixw.iloc[i - 1]) / 100
        T = 5 / 252
        sig = v * math.sqrt(T)
        cash_r = cashw.iloc[i] / cashw.iloc[i - 1] - 1
        if kind == "covered_call":
            K = S0 * math.exp(sig)
            prem = bs_call(S0, K, T, v) * 0.95
            r = (min(S1, K) + prem) / S0 - 1
        else:  # cash-secured put: put price via put-call parity (r ~ 0 over a week)
            K = S0 * math.exp(-sig)
            put = bs_call(S0, K, T, v) - S0 + K
            prem = max(put, 0) * 0.95
            r = cash_r + (prem - max(K - S1, 0)) / K
        rets.append(r); dates.append(weeks.index[i])
    s = pd.Series(rets, index=dates)
    cash = cashw.pct_change().reindex(s.index).fillna(0)
    sub = s[s.index >= EVAL_START]
    eq = (1 + sub).cumprod()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    yearly = (1 + sub).groupby(sub.index.year).prod() - 1
    sharpe = (sub - cash[cash.index >= EVAL_START]).mean() / sub.std() * math.sqrt(52)
    return {
        "cagr_pct": round((eq.iloc[-1] ** (1 / years) - 1) * 100, 1),
        "max_drawdown_pct": round(((eq / eq.cummax() - 1).min()) * 100, 1),
        "volatility_pct": round(sub.std() * math.sqrt(52) * 100, 1),
        "sharpe": round(float(sharpe), 2),
        "worst_year_pct": round(yearly.min() * 100, 1), "worst_year": int(yearly.idxmin()),
        "best_year_pct": round(yearly.max() * 100, 1),
        "y2020_pct": round(yearly.get(2020, np.nan) * 100, 1),
        "y2022_pct": round(yearly.get(2022, np.nan) * 100, 1),
        "final_10k": int(round(10000 * eq.iloc[-1], -1)),
        "positive_years": f"{int((yearly > 0).sum())}/{len(yearly)}",
        "weeks_breached_pct": round(float((sub < -0.0001).mean()) * 100, 1),
        "trades_per_year": 52.0,
        "modelled": True,
    }


def main():
    synthetic = "--synthetic" in sys.argv
    px = load_prices(synthetic)
    cols = ["SPY", "QQQ", "EFA", "AGG", "GLD", "BIL"]
    P = px[cols]
    cash_d = P["BIL"].pct_change().fillna(0)
    spy = P["SPY"]
    res = {}

    def W(**kw):
        return pd.DataFrame({c: kw.get(c, 0.0) for c in cols}, index=P.index, dtype=float)

    # 1 Buy and hold SPY (benchmark)
    w = W(SPY=1.0); d, t = run_weights(P, w)
    res["buy_hold"] = stats(d, cash_d, pd.Series(1.0, index=P.index), t)

    # 2 Rebalancing bot: 60/40 SPY/AGG, rebalanced monthly
    w = W(); me = P.index.to_series().groupby(P.index.to_period("M")).transform("max") == P.index.to_series()
    w.loc[me, "SPY"] = 0.6; w.loc[me, "AGG"] = 0.4; w.loc[~me] = np.nan
    w = w.ffill().fillna(0)
    # drift between rebalances: emulate by holding weights (daily-rebalanced approximation)
    d, t = run_weights(P, w); res["rebalance_60_40"] = stats(d, cash_d, pd.Series(0.6, index=P.index), t)
    res["rebalance_60_40"]["trades_per_year"] = 12.0  # monthly rebalance back to 60/40

    # 3 Trend filter: SPY above 200-day average, else cash (BIL)
    sma200 = spy.rolling(200).mean()
    on = (spy > sma200).astype(float)
    w = W(); w["SPY"] = on; w["BIL"] = 1 - on
    d, t = run_weights(P, w); res["trend_200"] = stats(d, cash_d, on, t)

    # 4 Moving-average crossover 50/200
    on = (spy.rolling(50).mean() > sma200).astype(float)
    w = W(); w["SPY"] = on; w["BIL"] = 1 - on
    d, t = run_weights(P, w); res["ma_cross"] = stats(d, cash_d, on, t)

    # 5 Momentum rotation (Composer-style): monthly, top 2 of SPY/QQQ/EFA/GLD by 6-month return; AGG if negative
    mom6 = P[["SPY", "QQQ", "EFA", "GLD"]].pct_change(126)
    w = W(); inv = pd.Series(0.0, index=P.index)
    for dt in P.index[me]:
        m = mom6.loc[dt].dropna().sort_values(ascending=False)
        if len(m) < 4:
            continue
        top = [k for k in m.index[:2] if m[k] > 0]
        row = {c: 0.0 for c in cols}
        for k in top:
            row[k] = 0.5
        row["AGG"] += 0.5 * (2 - len(top))
        w.loc[dt] = pd.Series(row)
    w.loc[~me] = np.nan; w = w.ffill().fillna(0)
    inv = w[["SPY", "QQQ", "EFA", "GLD"]].sum(axis=1)
    d, t = run_weights(P, w); res["momentum_rotation"] = stats(d, cash_d, inv, t)

    # 6 Dual momentum (global equities momentum with bond fallback): monthly, 12-month lookback
    m12 = P.pct_change(252)
    w = W()
    for dt in P.index[me]:
        if np.isnan(m12.loc[dt, "SPY"]):
            continue
        row = {c: 0.0 for c in cols}
        if m12.loc[dt, "SPY"] > m12.loc[dt, "BIL"]:
            row["SPY" if m12.loc[dt, "SPY"] >= m12.loc[dt, "EFA"] else "EFA"] = 1.0
        else:
            row["AGG"] = 1.0
        w.loc[dt] = pd.Series(row)
    w.loc[~me] = np.nan; w = w.ffill().fillna(0)
    d, t = run_weights(P, w); res["dual_momentum"] = stats(d, cash_d, w["SPY"] + w["EFA"], t)

    # 7 RSI(2) mean reversion: buy dips in an uptrend, exit on bounce above 5-day average
    r2 = rsi(spy, 2); sma5 = spy.rolling(5).mean()
    pos = pd.Series(0.0, index=P.index); holding = False
    for dt in P.index:
        if not holding and r2.get(dt, 50) < 10 and spy[dt] > sma200.get(dt, np.inf):
            holding = True
        elif holding and spy[dt] > sma5[dt]:
            holding = False
        pos[dt] = 1.0 if holding else 0.0
    w = W(); w["SPY"] = pos; w["BIL"] = 1 - pos
    d, t = run_weights(P, w); res["rsi_reversion"] = stats(d, cash_d, pos, t)

    # 8 Volatility regime (eToro agent example): out of stocks when VIX > 25, back in when VIX < 20
    vix = px["^VIX"]; pos = pd.Series(1.0, index=P.index); inside = True
    for dt in P.index:
        v = vix[dt]
        if inside and v > 25:
            inside = False
        elif not inside and v < 20:
            inside = True
        pos[dt] = 1.0 if inside else 0.0
    w = W(); w["SPY"] = pos; w["AGG"] = 1 - pos
    d, t = run_weights(P, w); res["vix_regime"] = stats(d, cash_d, pos, t)

    # 9 Risk breaker (Composer example): SPY down >3% over 10 days -> 50% T-bills / 50% gold
    drop = spy.pct_change(10) < -0.03
    w = W(); w["SPY"] = (~drop).astype(float); w["BIL"] = drop * 0.5; w["GLD"] = drop * 0.5
    d, t = run_weights(P, w); res["risk_breaker"] = stats(d, cash_d, (~drop).astype(float), t)

    # 10 Grid (Pionex/3Commas style, on SPY): start 50% invested; each 2% fall buys 10%, each 2% rise sells 10%
    pos = pd.Series(0.0, index=P.index); weight = 0.5; anchor = None
    for dt in P.index:
        p = spy[dt]
        if anchor is None:
            anchor = p
        while p <= anchor * 0.98 and weight < 1.0:
            weight = min(1.0, weight + 0.1); anchor *= 0.98
        while p >= anchor * 1.02 and weight > 0.0:
            weight = max(0.0, weight - 0.1); anchor *= 1.02
        if p >= anchor * 1.02 and weight == 0.0:
            anchor = p
        if p <= anchor * 0.98 and weight == 1.0:
            anchor = p
        pos[dt] = weight
    w = W(); w["SPY"] = pos; w["BIL"] = 1 - pos
    d, t = run_weights(P, w); res["grid"] = stats(d, cash_d, pos, t)

    # 11 DCA: equal monthly contributions into SPY vs investing everything on day one
    sub = spy[spy.index >= EVAL_START]
    firsts = sub.groupby(sub.index.to_period("M")).head(1)
    units = (1.0 / firsts).sum(); invested = len(firsts)
    dca_value = units * sub.iloc[-1]
    lump_value = invested * sub.iloc[-1] / sub.iloc[0]
    res["dca"] = {"months": int(invested), "dca_multiple": round(float(dca_value / invested), 2),
                  "lump_sum_multiple": round(float(lump_value / invested), 2),
                  "note": "Value per €1 contributed: monthly buying vs investing the same total on the first day."}

    # 12-13 Modelled weekly options strategies
    res["covered_call"] = options_weekly(px, "covered_call")
    res["cash_secured_put"] = options_weekly(px, "csp")

    out = {
        "updated": date.today().isoformat(),
        "period": f"{EVAL_START} to {P.index[-1].date().isoformat()}",
        "method": "Daily dividend-adjusted closes; signals use the close and trade at the next close (no look-ahead); 0.05% cost per unit traded; cash earns T-bill return (BIL). Options strategies are modelled with Black-Scholes using VIX as implied volatility, ~1 sigma out of the money, 5% premium haircut.",
        "source": "Computed from daily prices; only aggregated results are published.",
        "synthetic": synthetic,
        "results": res,
    }
    if synthetic:
        print(json.dumps(out, indent=1)[:3000])
        return
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
