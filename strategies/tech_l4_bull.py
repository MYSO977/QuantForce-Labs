#!/usr/bin/env python3
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
import pandas as pd
from .base import BaseStrategy, StrategyResult

log = logging.getLogger(__name__)
ET  = ZoneInfo("America/New_York")

class TechL4Bull(BaseStrategy):
    name="tech_l4_bull"; version="1.0"; signal_type="tech"; min_score=7.5
    RVOL_MIN=2.0; PRICE_MIN=5.0; PRICE_MAX=800.0; MIN_VOL=300_000

    def is_primary(self): return True

    def analyze(self, ticker, df1m, df5m, df1d) -> Optional[StrategyResult]:
        try:
            if df1m.empty or len(df1m)<10 or df5m.empty or len(df5m)<30: return None
            price = float(df1m["Close"].iloc[-1])
            open_ = float(df1m["Open"].iloc[0])
            if not (self.PRICE_MIN <= price <= self.PRICE_MAX): return None
            if float(df1m["Volume"].mean())*390 < self.MIN_VOL: return None

            now_et  = datetime.now(ET)
            elapsed = max((now_et.hour*60+now_et.minute)-(9*60+30), 1)
            cum_vol = float(df1m["Volume"].sum())
            avg_now = float(df1d["Volume"].iloc[:-1].mean())*(elapsed/390) if len(df1d)>=2 else cum_vol
            rvol    = cum_vol/avg_now if avg_now>0 else 0
            if rvol < self.RVOL_MIN: return None

            df1m = df1m.copy()
            df1m["tp"]  = (df1m["High"]+df1m["Low"]+df1m["Close"])/3
            df1m["tpv"] = df1m["tp"]*df1m["Volume"]
            vwap = float(df1m["tpv"].cumsum().iloc[-1]/df1m["Volume"].cumsum().iloc[-1])
            if price <= vwap: return None

            c5   = df5m["Close"]
            ema9 = c5.ewm(span=9, adjust=False).mean()
            if float(ema9.iloc[-1]) <= float(ema9.iloc[-2]): return None

            macd = float((c5.ewm(span=12,adjust=False).mean()-c5.ewm(span=26,adjust=False).mean()).iloc[-1])
            if macd <= 0: return None
            if price <= open_: return None

            return StrategyResult(
                ticker=ticker, price=round(price,2), score=7.5,
                rvol=round(rvol,2), vwap=round(vwap,2), macd=round(macd,4),
                meta={"open": round(open_,2)}
            )
        except Exception as e:
            log.debug(f"{ticker} 分析失败: {e}")
            return None
