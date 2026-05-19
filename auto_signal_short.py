#!/usr/bin/env python3
"""
auto_signal_short.py — 단기 v2 신호 + 통합 JSON 생성
====================================================

매일 KST 07:30, 22:30 실행 (장기 07:17, 22:17 + 13분 후)

작업 흐름:
  1. yfinance fetch: SPX, VIX, VIX3M, VIX9D, VVIX, SKEW, NDX, RUT,
                     HYG, TLT, XLP, XLY, DXY, TNX, KRE, IWM, SOXX
  2. v2 단기 신호 계산 (3M ±10% 시간 지평)
  3. 컨텍스트 알람 계산 (KRE, SOXX, IWM)
  4. 장기 저장소 data.json fetch
  5. 충돌 신호 계산
  6. data_short.json + data_unified.json 저장
  7. Telegram 알림 (레벨 변경 시)

GitHub Actions Secrets 필요:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
import yfinance as yf

# ──────────────────────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────────────────────
LONG_TERM_DATA_URL = "https://raw.githubusercontent.com/mryang82/market-signal-monitor-auto/main/data.json"

STATE_FILE = Path("previous_signal_short.json")
DATA_SHORT_FILE = Path("data_short.json")
DATA_UNIFIED_FILE = Path("data_unified.json")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ──────────────────────────────────────────────────────────────
# yfinance fetch
# ──────────────────────────────────────────────────────────────
TICKERS = {
    "^GSPC": "SPX",
    "^VIX": "VIX",
    "^VIX3M": "VIX3M",
    "^VIX9D": "VIX9D",
    "^VVIX": "VVIX",
    "^SKEW": "SKEW",
    "^NDX": "NDX",
    "^RUT": "RUT",
    "^TNX": "TNX",
    "HYG": "HYG",
    "TLT": "TLT",
    "XLP": "XLP",
    "XLY": "XLY",
    "DX-Y.NYB": "DXY",
    "KRE": "KRE",
    "IWM": "IWM",
    "SOXX": "SOXX",
}


def fetch_yfinance(period="6mo"):
    """yfinance에서 6개월치 데이터 일괄 다운로드"""
    print(f"📡 yfinance fetch (period={period})...")
    data = {}
    failed = []
    for ticker, name in TICKERS.items():
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period, auto_adjust=False)
            if hist is None or len(hist) == 0:
                failed.append(name)
                continue
            data[name] = hist["Close"].dropna()
        except Exception as e:
            print(f"   ❌ {name}: {str(e)[:50]}")
            failed.append(name)
    
    print(f"   ✓ {len(data)}/{len(TICKERS)} 성공")
    if failed:
        print(f"   ⚠️  실패: {failed}")
    return data


def safe_last(series):
    if series is None or len(series) == 0:
        return None
    return float(series.iloc[-1])


def safe_pct_change(series, n):
    """n일 전 대비 % 변화"""
    if series is None or len(series) < n + 1:
        return None
    cur = series.iloc[-1]
    past = series.iloc[-1 - n]
    if past == 0 or pd.isna(past):
        return None
    return float((cur / past - 1) * 100)


def safe_bp_change(series, n):
    """n일 전 대비 bp 변화 (TNX 같은 yield 변화)"""
    if series is None or len(series) < n + 1:
        return None
    cur = series.iloc[-1]
    past = series.iloc[-1 - n]
    return float((cur - past) * 100)  # %포인트 → bp


# ──────────────────────────────────────────────────────────────
# v2 단기 신호 엔진 (4-Pillar)
# ──────────────────────────────────────────────────────────────

def compute_v2_signal(d):
    """v2 단기 신호 계산
    
    Returns:
        dict with level, score, pillars, triggers_buy, triggers_sell
    """
    spx_5d = d.get("SPX_5d_chg")
    spx_20d = d.get("SPX_20d_chg")
    spx_ma50_pct = d.get("SPX_pct_above_MA50")
    spx_ma200_pct = d.get("SPX_pct_above_MA200")
    vix = d.get("VIX")
    vix_5d = d.get("VIX_5d_chg")
    vix3m_ratio = d.get("VIX_VIX3M_ratio")
    vvix = d.get("VVIX")
    skew = d.get("SKEW")
    hyg_5d = d.get("HYG_5d_chg")
    xlp_xly_20d = d.get("XLP_XLY_20d_chg")
    dxy_20d = d.get("DXY_20d_chg")
    tnx_5d_bp = d.get("TNX_5d_chg_bp")
    
    triggers_buy = []
    triggers_sell = []
    
    # ── 매수 트리거 (패닉 기반) ──
    if vix is not None and vix > 30:
        triggers_buy.append(("VIX > 30 (panic)", 3))
    if spx_ma200_pct is not None and spx_ma200_pct < -15:
        triggers_buy.append(("SPX < MA200 -15%", 3))
    if spx_5d is not None and spx_5d < -5:
        triggers_buy.append(("SPX 5d < -5%", 3))
    
    if vix is not None and 25 <= vix <= 30:
        triggers_buy.append(("VIX 25-30", 2))
    if spx_ma200_pct is not None and -15 <= spx_ma200_pct < -10:
        triggers_buy.append(("SPX MA200 -10~-15%", 2))
    if vix3m_ratio is not None and vix3m_ratio > 1.05:
        triggers_buy.append(("VIX/VIX3M > 1.05 (deep BW)", 2))
    if spx_5d is not None and -5 <= spx_5d < -3:
        triggers_buy.append(("SPX 5d -3~-5%", 2))
    
    if vix3m_ratio is not None and 1.00 < vix3m_ratio <= 1.05:
        triggers_buy.append(("VIX/VIX3M > 1.0 (BW)", 1))
    if hyg_5d is not None and hyg_5d > 1.5:
        triggers_buy.append(("HYG 5d > +1.5%", 1))
    if vvix is not None and vvix > 120:
        triggers_buy.append(("VVIX > 120", 1))
    
    # ── 매도 트리거 (4-Pillar 모멘텀 기반) ──
    pillar_A = 0  # Price Momentum
    if spx_20d is not None and spx_20d < -5:
        triggers_sell.append(("SPX 20d < -5%", 3, "A"))
        pillar_A = 3
    elif spx_20d is not None and spx_20d < -3:
        triggers_sell.append(("SPX 20d < -3%", 2, "A"))
        pillar_A = 2
    if spx_5d is not None and spx_5d < -4 and pillar_A < 3:
        triggers_sell.append(("SPX 5d < -4%", 3, "A"))
        pillar_A = max(pillar_A, 3)
    if spx_ma50_pct is not None and spx_ma50_pct < -3 and pillar_A < 2:
        triggers_sell.append(("SPX < MA50 -3%", 1, "A"))
        pillar_A = max(pillar_A, 1)
    
    pillar_B = 0  # Drawdown Depth
    if spx_ma200_pct is not None:
        if -10 < spx_ma200_pct < -5:
            triggers_sell.append(("SPX MA200 -5~-10% (downtrend)", 2, "B"))
            pillar_B = 2
        elif -5 <= spx_ma200_pct < -2:
            triggers_sell.append(("SPX MA200 -2~-5%", 1, "B"))
            pillar_B = 1
    
    pillar_C = 0  # Credit & Rotation
    if hyg_5d is not None and hyg_5d < -1.5:
        triggers_sell.append(("HYG 5d < -1.5% (credit stress)", 3, "C"))
        pillar_C = 3
    elif hyg_5d is not None and hyg_5d < -0.8:
        triggers_sell.append(("HYG 5d < -0.8%", 2, "C"))
        pillar_C = 2
    if xlp_xly_20d is not None and xlp_xly_20d > 4:
        triggers_sell.append(("XLP/XLY 20d > +4% (defensive rotation)", 3, "C"))
        pillar_C = max(pillar_C, 3)
    elif xlp_xly_20d is not None and xlp_xly_20d > 2:
        triggers_sell.append(("XLP/XLY 20d > +2%", 1, "C"))
        pillar_C = max(pillar_C, 1)
    
    pillar_D = 0  # Macro Stress
    if dxy_20d is not None and dxy_20d > 3:
        triggers_sell.append(("DXY 20d > +3% (USD strength)", 2, "D"))
        pillar_D = 2
    if vix is not None and 18 <= vix <= 25:
        triggers_sell.append(("VIX 18-25 (elevated)", 1, "D"))
        pillar_D = max(pillar_D, 1)
    if skew is not None and skew > 145:
        triggers_sell.append(("SKEW > 145", 1, "D"))
        pillar_D = max(pillar_D, 1)
    
    # ── 신호 결합 ──
    buy_strong = sum(1 for _, w in triggers_buy if w >= 3)
    buy_medium = sum(1 for _, w in triggers_buy if w == 2)
    buy_weak = sum(1 for _, w in triggers_buy if w == 1)
    buy_score = sum(w for _, w in triggers_buy)
    
    sell_pillars_strong = sum(1 for p in [pillar_A, pillar_B, pillar_C, pillar_D] if p >= 2)
    sell_pillars_any = sum(1 for p in [pillar_A, pillar_B, pillar_C, pillar_D] if p >= 1)
    sell_score = -(pillar_A + pillar_B + pillar_C + pillar_D)
    
    if buy_strong >= 2:
        level = "PANIC_BUY"
        score = buy_score
    elif buy_strong >= 1:
        level = "SHIFT_UP"
        score = buy_score
    elif buy_medium >= 2:
        level = "SHIFT_UP"
        score = buy_score
    elif buy_medium >= 1:
        level = "CAUTION_UP"
        score = buy_score
    elif buy_weak >= 2:
        level = "CAUTION_UP"
        score = buy_score
    elif sell_pillars_strong >= 2:
        level = "SHIFT_DOWN"
        score = sell_score
    elif sell_pillars_strong >= 1 and sell_pillars_any >= 2:
        level = "CAUTION_DOWN"
        score = sell_score
    elif sell_pillars_any >= 2:
        level = "CAUTION_DOWN"
        score = sell_score
    else:
        level = "NEUTRAL"
        score = 0
    
    return {
        "level": level,
        "score": score,
        "pillar_A": pillar_A,
        "pillar_B": pillar_B,
        "pillar_C": pillar_C,
        "pillar_D": pillar_D,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "triggers_buy": [{"name": t[0], "weight": t[1]} for t in triggers_buy],
        "triggers_sell": [{"name": t[0], "weight": t[1], "pillar": t[2]} for t in triggers_sell],
    }


# ──────────────────────────────────────────────────────────────
# 컨텍스트 알람 (KRE/SOXX/IWM)
# ──────────────────────────────────────────────────────────────

def compute_context_alerts(d):
    """위험 컨텍스트 알람 - 단독 알람용 (행동 권고 X, 정보 제공)"""
    alerts = []
    
    # KRE - 지방은행 스트레스
    kre_5d = d.get("KRE_5d_chg")
    kre_20d = d.get("KRE_20d_chg")
    if kre_20d is not None and kre_20d < -10:
        alerts.append({
            "id": "kre_20d",
            "level": "high",
            "title": "은행 스트레스",
            "desc": f"KRE 20일 {kre_20d:+.1f}% (지방은행 약세)",
            "backtest": "단독 -15% 도달 적중률 28%",
        })
    elif kre_5d is not None and kre_5d < -5:
        alerts.append({
            "id": "kre_5d",
            "level": "medium",
            "title": "은행 단기 스트레스",
            "desc": f"KRE 5일 {kre_5d:+.1f}%",
            "backtest": "단독 -15% 적중률 25%",
        })
    
    # SOXX - 반도체
    soxx_20d = d.get("SOXX_20d_chg")
    if soxx_20d is not None and soxx_20d < -10:
        alerts.append({
            "id": "soxx_20d",
            "level": "high",
            "title": "반도체 약세",
            "desc": f"SOXX 20일 {soxx_20d:+.1f}% (위험자산 선행)",
            "backtest": "단독 -15% 적중률 28%",
        })
    
    # IWM/SPX - 시장 폭 약화
    iwm_spx_20d = d.get("IWM_SPX_20d_chg")
    if iwm_spx_20d is not None and iwm_spx_20d < -5:
        alerts.append({
            "id": "iwm_spx",
            "level": "high",
            "title": "시장 폭 약화",
            "desc": f"IWM/SPX 20일 {iwm_spx_20d:+.1f}% (소형주만 약세)",
            "backtest": "단독 -15% 적중률 26%",
        })
    
    # VIX9D/VIX 백워데이션 (참고 정보)
    vix9d_ratio = d.get("VIX9D_VIX_ratio")
    if vix9d_ratio is not None:
        if vix9d_ratio > 1.10:
            alerts.append({
                "id": "vix9d_bw",
                "level": "medium",
                "title": "단기 백워데이션",
                "desc": f"VIX9D/VIX = {vix9d_ratio:.2f} (단기 패닉 임박)",
                "backtest": "단독 효과 약함 (참고용)",
            })
    
    return alerts


# ──────────────────────────────────────────────────────────────
# 충돌 신호 (장기 + 단기 결합)
# ──────────────────────────────────────────────────────────────

LONG_BUY_LEVELS = {"CRASH_BUY", "STRONG_BUY", "BUY", "WATCH"}
LONG_SELL_LEVELS = {"CAUTION", "WARNING", "STRONG_SELL"}
SHORT_BUY_LEVELS = {"PANIC_BUY", "SHIFT_UP", "CAUTION_UP"}
SHORT_SELL_LEVELS = {"SHIFT_DOWN", "CAUTION_DOWN"}


def compute_conflict(long_level, short_level):
    """장기 vs 단기 신호 충돌 분석"""
    if not long_level or not short_level:
        return {"type": "incomplete", "title": "장기 또는 단기 신호 미수신", "level": "info"}
    
    long_is_buy = long_level in LONG_BUY_LEVELS
    long_is_sell = long_level in LONG_SELL_LEVELS
    short_is_buy = short_level in SHORT_BUY_LEVELS
    short_is_sell = short_level in SHORT_SELL_LEVELS
    
    if long_is_buy and short_is_buy:
        return {
            "type": "buy_agree",
            "title": "✅ 매수 합의",
            "desc": f"장기 {long_level} + 단기 {short_level} — 강한 매수 신뢰 (백테스트 12M+15% 적중률 55%)",
            "level": "good",
        }
    if long_is_sell and short_is_sell:
        return {
            "type": "sell_agree",
            "title": "📉 매도 합의",
            "desc": f"장기 {long_level} + 단기 {short_level} — 단기 모멘텀 매도 신뢰",
            "level": "warn",
        }
    if long_is_buy and short_is_sell:
        return {
            "type": "conflict_buy_sell",
            "title": "⚠️ 충돌: 장기 매수 + 단기 매도",
            "desc": f"장기는 {long_level}이지만 단기 {short_level} — 백테스트 6M MDD-15% 적중 50%, 진입 보류 권고",
            "level": "danger",
        }
    if long_is_sell and short_is_buy:
        return {
            "type": "conflict_sell_buy",
            "title": "⚠️ 충돌: 장기 매도 + 단기 매수",
            "desc": f"장기 {long_level} + 단기 {short_level} — 단기 반등 가능하나 장기 위험",
            "level": "warn",
        }
    if long_is_buy:
        return {
            "type": "long_only_buy",
            "title": "장기만 매수",
            "desc": f"장기 {long_level} + 단기 중립 — 분할 매수 가능",
            "level": "info",
        }
    if short_is_buy:
        return {
            "type": "short_only_buy",
            "title": "단기만 매수",
            "desc": f"단기 {short_level} — 단기 반등 시도 (장기 신호 대기)",
            "level": "info",
        }
    if short_is_sell:
        return {
            "type": "short_only_sell",
            "title": "단기 매도",
            "desc": f"단기 {short_level} — 단기 비중 조절 (적중률 32~43%)",
            "level": "warn",
        }
    if long_is_sell:
        return {
            "type": "long_only_sell",
            "title": "장기만 매도 (참고)",
            "desc": f"장기 {long_level} (역사적으로 신뢰 낮음, 백테스트 16%)",
            "level": "info",
        }
    return {
        "type": "neutral",
        "title": "중립",
        "desc": "양쪽 신호 없음 — 현 포지션 유지",
        "level": "info",
    }


# ──────────────────────────────────────────────────────────────
# 장기 저장소 data.json fetch
# ──────────────────────────────────────────────────────────────

def fetch_long_term_data():
    """장기 저장소의 data.json fetch"""
    print(f"📡 장기 저장소 data.json fetch...")
    try:
        url = f"{LONG_TERM_DATA_URL}?t={int(datetime.now().timestamp())}"
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            print(f"   ❌ HTTP {r.status_code}")
            return None
        data = r.json()
        print(f"   ✓ 장기 신호: {data.get('level')} (score {data.get('score')})")
        return data
    except Exception as e:
        print(f"   ❌ {str(e)[:80]}")
        return None


# ──────────────────────────────────────────────────────────────
# 데이터 가공
# ──────────────────────────────────────────────────────────────

def build_indicators(market_data):
    """fetched market data → v2가 필요한 형식으로 변환"""
    d = {}
    
    # SPX
    spx = market_data.get("SPX")
    if spx is not None and len(spx) > 0:
        d["SPX"] = safe_last(spx)
        d["SPX_5d_chg"] = safe_pct_change(spx, 5)
        d["SPX_20d_chg"] = safe_pct_change(spx, 20)
        # MA50/MA200
        if len(spx) >= 50:
            ma50 = spx.rolling(50).mean()
            cur = spx.iloc[-1]
            ma50_val = ma50.iloc[-1]
            if not pd.isna(ma50_val) and ma50_val > 0:
                d["SPX_pct_above_MA50"] = float((cur / ma50_val - 1) * 100)
        if len(spx) >= 200:
            ma200 = spx.rolling(200).mean()
            cur = spx.iloc[-1]
            ma200_val = ma200.iloc[-1]
            if not pd.isna(ma200_val) and ma200_val > 0:
                d["SPX_pct_above_MA200"] = float((cur / ma200_val - 1) * 100)
    
    # VIX
    vix = market_data.get("VIX")
    if vix is not None and len(vix) > 0:
        d["VIX"] = safe_last(vix)
        d["VIX_5d_chg"] = safe_pct_change(vix, 5)
    
    vix3m = market_data.get("VIX3M")
    if vix3m is not None and len(vix3m) > 0 and d.get("VIX") is not None:
        d["VIX3M"] = safe_last(vix3m)
        if d["VIX3M"] > 0:
            d["VIX_VIX3M_ratio"] = d["VIX"] / d["VIX3M"]
    
    vix9d = market_data.get("VIX9D")
    if vix9d is not None and len(vix9d) > 0 and d.get("VIX") is not None:
        d["VIX9D"] = safe_last(vix9d)
        if d["VIX"] > 0:
            d["VIX9D_VIX_ratio"] = d["VIX9D"] / d["VIX"]
    
    vvix = market_data.get("VVIX")
    if vvix is not None and len(vvix) > 0:
        d["VVIX"] = safe_last(vvix)
    
    skew = market_data.get("SKEW")
    if skew is not None and len(skew) > 0:
        d["SKEW"] = safe_last(skew)
    
    # HYG
    hyg = market_data.get("HYG")
    if hyg is not None and len(hyg) > 0:
        d["HYG"] = safe_last(hyg)
        d["HYG_5d_chg"] = safe_pct_change(hyg, 5)
    
    # XLP/XLY 비율
    xlp = market_data.get("XLP")
    xly = market_data.get("XLY")
    if xlp is not None and xly is not None and len(xlp) > 20 and len(xly) > 20:
        ratio = xlp / xly
        d["XLP_XLY_ratio"] = float(ratio.iloc[-1])
        d["XLP_XLY_20d_chg"] = safe_pct_change(ratio, 20)
    
    # DXY
    dxy = market_data.get("DXY")
    if dxy is not None and len(dxy) > 0:
        d["DXY"] = safe_last(dxy)
        d["DXY_20d_chg"] = safe_pct_change(dxy, 20)
    
    # TNX
    tnx = market_data.get("TNX")
    if tnx is not None and len(tnx) > 0:
        d["TNX"] = safe_last(tnx)
        d["TNX_5d_chg_bp"] = safe_bp_change(tnx, 5)
    
    # KRE
    kre = market_data.get("KRE")
    if kre is not None and len(kre) > 0:
        d["KRE"] = safe_last(kre)
        d["KRE_5d_chg"] = safe_pct_change(kre, 5)
        d["KRE_20d_chg"] = safe_pct_change(kre, 20)
    
    # IWM/SPX 비율
    iwm = market_data.get("IWM")
    if iwm is not None and spx is not None and len(iwm) > 20 and len(spx) > 20:
        # 동일 인덱스로 정렬
        common = iwm.index.intersection(spx.index)
        if len(common) > 20:
            iwm_aligned = iwm.loc[common]
            spx_aligned = spx.loc[common]
            ratio = iwm_aligned / spx_aligned
            d["IWM_SPX_ratio"] = float(ratio.iloc[-1])
            d["IWM_SPX_20d_chg"] = safe_pct_change(ratio, 20)
    
    # SOXX
    soxx = market_data.get("SOXX")
    if soxx is not None and len(soxx) > 20:
        d["SOXX"] = safe_last(soxx)
        d["SOXX_20d_chg"] = safe_pct_change(soxx, 20)
    
    # NDX, RUT (참고)
    ndx = market_data.get("NDX")
    if ndx is not None and len(ndx) > 0:
        d["NDX"] = safe_last(ndx)
    rut = market_data.get("RUT")
    if rut is not None and len(rut) > 0:
        d["RUT"] = safe_last(rut)
    
    return d


# ──────────────────────────────────────────────────────────────
# Telegram
# ──────────────────────────────────────────────────────────────

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("   ⚠️  Telegram 자격증명 없음, 알림 생략")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.status_code == 200
    except Exception as e:
        print(f"   ❌ Telegram 실패: {e}")
        return False


LEVEL_EMOJI = {
    "PANIC_BUY": "🚀",
    "SHIFT_UP": "📈",
    "CAUTION_UP": "🟢",
    "NEUTRAL": "⚪",
    "CAUTION_DOWN": "🟡",
    "SHIFT_DOWN": "🔴",
}


def format_telegram_message(short_sig, long_data, conflict, alerts, indicators):
    """Telegram 알림 메시지 생성"""
    short_emoji = LEVEL_EMOJI.get(short_sig["level"], "⚪")
    
    lines = []
    lines.append(f"{short_emoji} <b>단기 {short_sig['level']}</b>")
    lines.append(f"점수: {short_sig['score']:+d}")
    lines.append("")
    
    # 장기 신호
    if long_data:
        lines.append(f"📊 장기: <b>{long_data.get('level', '?')}</b> (점수 {long_data.get('score', 0):+.1f})")
    else:
        lines.append("📊 장기: 신호 없음")
    
    # 충돌
    if conflict["level"] in ("danger", "warn"):
        lines.append("")
        lines.append(conflict["title"])
        lines.append(f"<i>{conflict['desc']}</i>")
    elif conflict["type"] in ("buy_agree", "sell_agree"):
        lines.append("")
        lines.append(conflict["title"])
    
    # 활성 트리거 (단기)
    if short_sig["triggers_buy"]:
        lines.append("")
        lines.append("📈 <b>매수 트리거:</b>")
        for t in short_sig["triggers_buy"][:5]:
            lines.append(f"  • {t['name']}")
    if short_sig["triggers_sell"]:
        lines.append("")
        lines.append("📉 <b>매도 트리거:</b>")
        for t in short_sig["triggers_sell"][:5]:
            lines.append(f"  • [{t['pillar']}] {t['name']}")
    
    # 컨텍스트 알람
    if alerts:
        lines.append("")
        lines.append("⚠️ <b>위험 컨텍스트:</b>")
        for a in alerts:
            lines.append(f"  • {a['title']}: {a['desc']}")
    
    # 핵심 지표
    lines.append("")
    lines.append("📊 핵심 지표:")
    if indicators.get("SPX"):
        lines.append(f"  SPX: {indicators['SPX']:.0f} (5d {indicators.get('SPX_5d_chg', 0):+.1f}%, 20d {indicators.get('SPX_20d_chg', 0):+.1f}%)")
    if indicators.get("VIX"):
        vix_str = f"  VIX: {indicators['VIX']:.1f}"
        if indicators.get("VIX_VIX3M_ratio"):
            vix_str += f" (VIX/3M {indicators['VIX_VIX3M_ratio']:.2f})"
        lines.append(vix_str)
    if indicators.get("HYG_5d_chg") is not None:
        lines.append(f"  HYG 5d: {indicators['HYG_5d_chg']:+.1f}%")
    
    lines.append("")
    lines.append(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')} KST")
    
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# State 관리
# ──────────────────────────────────────────────────────────────

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_level": None, "last_run": None}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


# ──────────────────────────────────────────────────────────────
# JSON 출력
# ──────────────────────────────────────────────────────────────

def export_data_short(short_sig, indicators, alerts):
    """단기 신호 JSON 출력"""
    return {
        "timestamp": datetime.now().isoformat(),
        "level": short_sig["level"],
        "score": short_sig["score"],
        "buy_score": short_sig["buy_score"],
        "sell_score": short_sig["sell_score"],
        "pillars": {
            "A_price_momentum": short_sig["pillar_A"],
            "B_drawdown": short_sig["pillar_B"],
            "C_credit_rotation": short_sig["pillar_C"],
            "D_macro_stress": short_sig["pillar_D"],
        },
        "triggers_buy": short_sig["triggers_buy"],
        "triggers_sell": short_sig["triggers_sell"],
        "context_alerts": alerts,
        "indicators": indicators,
        "backtest": {
            "PANIC_BUY": {"hit_rate_3m_up10": 55.6, "n": 293},
            "SHIFT_UP": {"hit_rate_3m_up10": 48.9, "n": 689},
            "CAUTION_UP": {"hit_rate_3m_up10": 31.1, "n": 753},
            "CAUTION_DOWN": {"hit_rate_3m_dn10": 31.8, "n": 877},
            "SHIFT_DOWN": {"hit_rate_3m_dn10": 42.8, "n": 334},
        },
    }


def export_data_unified(short_data, long_data, conflict):
    """통합 JSON 출력"""
    return {
        "timestamp": datetime.now().isoformat(),
        "short_term": short_data,
        "long_term": long_data,
        "conflict": conflict,
        "version": "v12",
    }


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("auto_signal_short.py — v12 단기 + 통합")
    print(f"실행 시각: {datetime.now().isoformat()}")
    print("=" * 70)
    
    # 1. yfinance fetch
    market_data = fetch_yfinance(period="6mo")
    if not market_data.get("SPX") or not market_data.get("VIX"):
        print("\n❌ 필수 데이터 (SPX, VIX) 없음 — 종료")
        sys.exit(1)
    
    # 2. 지표 계산
    print("\n🧮 지표 계산...")
    indicators = build_indicators(market_data)
    print(f"   계산된 지표 {len(indicators)}개")
    for k in ["SPX", "VIX", "SPX_5d_chg", "SPX_20d_chg", "VIX_VIX3M_ratio",
              "HYG_5d_chg", "KRE_20d_chg", "SOXX_20d_chg", "IWM_SPX_20d_chg"]:
        v = indicators.get(k)
        if v is not None:
            print(f"   {k}: {v:.2f}")
    
    # 3. v2 신호 계산
    print("\n🚦 v2 단기 신호 계산...")
    short_sig = compute_v2_signal(indicators)
    print(f"   ⇒ 신호: {short_sig['level']} (score {short_sig['score']:+d})")
    print(f"   Pillars: A={short_sig['pillar_A']} B={short_sig['pillar_B']} C={short_sig['pillar_C']} D={short_sig['pillar_D']}")
    
    # 4. 컨텍스트 알람
    alerts = compute_context_alerts(indicators)
    if alerts:
        print(f"\n⚠️  활성 컨텍스트 알람 {len(alerts)}개:")
        for a in alerts:
            print(f"   • [{a['level']}] {a['title']}: {a['desc']}")
    
    # 5. 장기 저장소 data.json fetch
    long_data = fetch_long_term_data()
    
    # 6. 충돌 신호
    print("\n🤝 충돌 신호 계산...")
    long_level = long_data.get("level") if long_data else None
    conflict = compute_conflict(long_level, short_sig["level"])
    print(f"   ⇒ {conflict['title']}")
    
    # 7. JSON 출력
    print("\n💾 JSON 저장...")
    data_short = export_data_short(short_sig, indicators, alerts)
    DATA_SHORT_FILE.write_text(json.dumps(data_short, indent=2, default=str))
    print(f"   ✓ {DATA_SHORT_FILE}")
    
    data_unified = export_data_unified(data_short, long_data, conflict)
    DATA_UNIFIED_FILE.write_text(json.dumps(data_unified, indent=2, default=str))
    print(f"   ✓ {DATA_UNIFIED_FILE}")
    
    # 8. Telegram 알림 (단기 레벨 변경 또는 충돌 발생 시)
    state = load_state()
    last_level = state.get("last_level")
    last_conflict = state.get("last_conflict_type")
    
    notify_reasons = []
    if last_level != short_sig["level"]:
        notify_reasons.append(f"레벨 변경: {last_level} → {short_sig['level']}")
    if conflict["type"] != last_conflict and conflict["level"] in ("danger", "warn"):
        notify_reasons.append(f"충돌 신호: {conflict['type']}")
    
    if notify_reasons:
        print(f"\n📨 Telegram 알림 발송: {notify_reasons}")
        msg = format_telegram_message(short_sig, long_data, conflict, alerts, indicators)
        ok = send_telegram(msg)
        print(f"   {'✓ 발송 성공' if ok else '❌ 발송 실패'}")
    else:
        print(f"\n🔕 알림 조건 미충족 (현 레벨 유지: {short_sig['level']})")
    
    # 9. State 저장
    save_state({
        "last_level": short_sig["level"],
        "last_run": datetime.now().isoformat(),
        "last_conflict_type": conflict["type"],
    })
    
    print("\n✅ 완료")


if __name__ == "__main__":
    main()
