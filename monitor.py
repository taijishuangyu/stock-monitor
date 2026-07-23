#!/usr/bin/env python3
"""
GitHub Actions 版 A股监测脚本
- 每5分钟由 GitHub Actions cron 触发
- 检测12只目标个股的5分钟K线
- 信号通过 PushPlus 推送微信
- 状态通过 GitHub Artifacts 持久化（跨运行保持）
"""

import os
import json
import sys
import requests
from datetime import datetime, timezone, timedelta
from collections import deque
from pathlib import Path

# ═══════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════

TARGET_STOCKS = {
    "600396": "华电辽能", "000722": "湖南发展", "603979": "金诚信",
    "601168": "西部矿业", "600236": "桂冠电力", "601212": "白银有色",
    "000938": "紫光股份", "000977": "浪潮信息", "001258": "立新能源",
    "600664": "哈药股份", "603118": "共进股份", "002396": "星网锐捷",
}

OBV_FAST = 6
OBV_SLOW = 20
MA1 = 48
MA2 = 60
MAX_KLINE = 200

# PushPlus Token（通过 GitHub Secrets 传入）
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")

# 状态文件路径
STATE_FILE = Path("monitor_state.json")
BEIJING_TZ = timezone(timedelta(hours=8))

# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════

def now_str():
    return datetime.now(BEIJING_TZ).strftime("%H:%M:%S")

def today_str():
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")

def is_trading_time():
    now = datetime.now(BEIJING_TZ)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (t >= datetime.strptime("09:20", "%H:%M").time() and
            t <= datetime.strptime("15:05", "%H:%M").time())

# ═══════════════════════════════════════════════════════
# 数据获取
# ═══════════════════════════════════════════════════════

def get_klines(code):
    """新浪财经5分钟K线（统一数据源）"""
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": f"{prefix}{code}", "scale": "5", "ma": "no", "datalen": "200"}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        if data:
            return [{"time": d["day"], "open": float(d["open"]), "close": float(d["close"]),
                     "high": float(d["high"]), "low": float(d["low"]), "volume": float(d["volume"])} for d in data]
    except:
        pass
    
    # 备用：akshare
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist_min_em(symbol=code, period='5', adjust='')
        if df is not None and not df.empty:
            return [{"time": r["时间"], "open": r["开盘"], "close": r["收盘"],
                     "high": r["最高"], "low": r["最低"], "volume": r["成交量"]}
                    for _, r in df.iterrows()]
    except:
        pass
    return []

# ═══════════════════════════════════════════════════════
# 指标计算
# ═══════════════════════════════════════════════════════

def calc_obv(klines):
    n = len(klines)
    obv = [0.0] * n
    for i in range(1, n):
        obv[i] = obv[i-1] + klines[i]["volume"] if klines[i]["close"] >= klines[i-1]["close"] else obv[i-1] - klines[i]["volume"]
    return obv

def calc_ma(values, period):
    n = len(values)
    if n < period:
        return [None] * n
    r = [None] * (period - 1)
    w = deque(maxlen=period)
    for i in range(period - 1):
        w.append(values[i])
    for i in range(period - 1, n):
        w.append(values[i])
        r.append(sum(w) / period)
    return r

def find_obv_crosses(klines):
    """OBV_MA6 上穿 OBV_MA20"""
    n = len(klines)
    if n < OBV_SLOW + 2:
        return []
    obv = calc_obv(klines)
    ma6 = calc_ma(obv, OBV_FAST)
    ma20 = calc_ma(obv, OBV_SLOW)
    crosses = []
    for i in range(1, n):
        if (ma6[i-1] and ma20[i-1] and ma6[i] and ma20[i]):
            if ma6[i-1] <= ma20[i-1] and ma6[i] > ma20[i]:
                crosses.append({
                    "time": klines[i]["time"],
                    "close": klines[i]["close"],
                    "ma6": round(ma6[i], 2),
                    "ma20": round(ma20[i], 2),
                })
    return crosses

def find_ma_downturns(klines):
    """MA48&MA60 双跌拐点：当前双跌，前一周期至少一线上涨"""
    n = len(klines)
    if n < MA2 + 2:
        return []
    closes = [k["close"] for k in klines]
    ma48 = calc_ma(closes, MA1)
    ma60 = calc_ma(closes, MA2)
    turns = []
    for i in range(2, n):
        if (ma48[i-2] and ma60[i-2] and ma48[i-1] and ma60[i-1] and ma48[i] and ma60[i]):
            curr_both_down = ma48[i-1] > ma48[i] and ma60[i-1] > ma60[i]
            prev_any_up = ma48[i-2] < ma48[i-1] or ma60[i-2] < ma60[i-1]
            if curr_both_down and prev_any_up:
                turns.append({
                    "time": klines[i]["time"],
                    "close": klines[i]["close"],
                    "ma48_p": round(ma48[i-1], 2),
                    "ma48_c": round(ma48[i], 2),
                    "ma60_p": round(ma60[i-1], 2),
                    "ma60_c": round(ma60[i], 2),
                })
    return turns

# ═══════════════════════════════════════════════════════
# 通知
# ═══════════════════════════════════════════════════════

def send_pushplus(sig_type, code, name, detail):
    if not PUSHPLUS_TOKEN:
        print(f"  [无Token] {sig_type} {name}({code}): {detail}")
        return
    try:
        icon = "🔴" if sig_type == "卖出" else "🟢"
        payload = {
            "token": PUSHPLUS_TOKEN,
            "title": f"{icon} {sig_type}信号 - {name}({code})",
            "content": f"## {icon} {sig_type}信号\n\n**个股**: {name} ({code})\n\n**时间**: {now_str()}\n\n**详情**: {detail}",
            "template": "markdown",
        }
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        if r.status_code == 200 and r.json().get("code") == 200:
            print(f"  ✅ 微信推送成功")
        else:
            print(f"  ⚠ 推送失败: {r.text[:100]}")
    except Exception as e:
        print(f"  ⚠ 推送异常: {e}")

# ═══════════════════════════════════════════════════════
# 主逻辑
# ═══════════════════════════════════════════════════════

def main():
    print(f"═══════════════════════════════════════")
    print(f"  A股监测 (GitHub Actions)")
    print(f"  时间: {datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"═══════════════════════════════════════")

    if not is_trading_time():
        print("⏸ 非交易时段，跳过")
        return

    print("🟢 交易时段，开始监测...\n")

    # 加载状态
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except:
            pass

    today = today_str()
    total = 0

    for code, name in TARGET_STOCKS.items():
        klines = get_klines(code)
        if not klines or len(klines) < 65:
            print(f"  {name}({code}): K线不足")
            continue

        # 买入信号
        crosses = [c for c in find_obv_crosses(klines) if c["time"].startswith(today)]
        buy_key = f"buy_{code}"
        for c in crosses:
            if state.get(buy_key) != c["time"]:
                detail = f"OBV_MA6({c['ma6']:.0f}) ↑穿 OBV_MA20({c['ma20']:.0f}) | 价={c['close']:.2f}"
                print(f"  🟢 [买入] {name}({code}) {c['time']} 价={c['close']:.2f}")
                send_pushplus("买入", code, name, detail)
                state[buy_key] = c["time"]
                total += 1

        # 卖出信号
        turns = [t for t in find_ma_downturns(klines) if t["time"].startswith(today)]
        sell_key = f"sell_{code}"
        for t in turns:
            if state.get(sell_key) != t["time"]:
                detail = f"MA48({t['ma48_p']}→{t['ma48_c']}) MA60({t['ma60_p']}→{t['ma60_c']}) 双跌拐点 | 价={t['close']:.2f}"
                print(f"  🔴 [卖出] {name}({code}) {t['time']} 价={t['close']:.2f}")
                send_pushplus("卖出", code, name, detail)
                state[sell_key] = t["time"]
                total += 1

        print(f"  {name}({code}): {len(klines)}根K线 OK")

    # 保存状态
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False))

    print(f"\n  本轮信号: {total} 个")
    print(f"═══════════════════════════════════════")

if __name__ == "__main__":
    main()
