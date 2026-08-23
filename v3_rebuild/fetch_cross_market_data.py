#!/usr/bin/env python3
import yfinance as yf
import pandas as pd
import json
from pathlib import Path

SYMBOLS = ['AAPL','ABNB','AMAT','AMD','AMZN','APP','AVGO','CHWY','COIN','COST','CRWD','DDOG','DKNG','DUOL','ELF','ESTC','ETSY','EXPE','GOOGL','GTLB','HD','HOOD','KLAC','LCID','LRCX','LULU','MDB','META','MRVL','MSFT','MU','NET','NFLX','NIO','NKE','NOW','NVDA','PANW','PAYO','PINS','PLTR','QCOM','QQQ','RIVN','ROKU','S','SHOP','SNAP','SNOW','SOFI','SPOT','SPY','SQ','TEAM','TSLA','TTD','UBER','UPST','VEEV','WMT','XPEV','ZS']
OUT=Path('/opt/stonk-ai/v3_rebuild/data/daily_bars_2022_2023.json')


def fetch_period(syms, start, end):
    data=yf.download(syms, start=start, end=end, auto_adjust=True, progress=False)
    data.index = pd.to_datetime(data.index, utc=True)
    dfs={}
    for sym in syms:
        try:
            sub=pd.DataFrame({
                'Close': data[('Close',sym)].values,
                'High': data[('High',sym)].values,
                'Low': data[('Low',sym)].values,
                'Open': data[('Open',sym)].values,
                'Volume': data[('Volume',sym)].values,
            }, index=data.index)
            sub=sub.dropna(subset=['Close'])
            if not sub.empty:
                dfs[sym]=sub
            else:
                print('empty', sym)
        except KeyError:
            print('missing', sym)
    return dfs


if __name__ == '__main__':
    result={}
    periods = [('2022_bear',('2022-01-01','2023-01-03')),('2023_trans',('2023-01-01','2024-09-01'))]
    for period, (start, end) in periods:
        print('fetching', period)
        dfs=fetch_period(SYMBOLS, start, end)
        qqq=dfs.get('QQQ')
        if qqq is None:
            raise ValueError('no QQQ')
        dates=qqq.index.strftime('%Y-%m-%dT%H:%M:%SZ').tolist()
        result[period]={}
        for sym in SYMBOLS:
            df=dfs.get(sym)
            if df is None:
                continue
            df=df.reindex(qqq.index)
            df['Close']=df['Close'].ffill()
            df['Open']=df['Open'].ffill()
            df['High']=df['High'].ffill()
            df['Low']=df['Low'].ffill()
            df['Volume']=df['Volume'].fillna(0)
            result[period][sym]={
                'timestamps':dates,
                'opens':df['Open'].astype(float).tolist(),
                'highs':df['High'].astype(float).tolist(),
                'lows':df['Low'].astype(float).tolist(),
                'closes':df['Close'].astype(float).tolist(),
                'volumes':df['Volume'].astype(float).tolist(),
            }
        print(period, 'dates', len(dates), dates[0], dates[-1], 'syms', len(result[period]))

    json.dump(result, open(OUT,'w'))
    print('saved', OUT, 'size MB', OUT.stat().st_size/1e6)
