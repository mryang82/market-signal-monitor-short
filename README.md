# market-signal-monitor-short

**v12 단기 신호 시스템** — v2 단기 매수/매도 + 컨텍스트 알람 + 장기 통합

## 🎯 시스템 구조

```
[장기 저장소: market-signal-monitor-auto]
  KST 07:17, 22:17 실행
  → data.json 생성

[단기 저장소: market-signal-monitor-short]  ⭐ 이 저장소
  KST 07:30, 22:30 실행 (장기 +13분)
  1. yfinance fetch (17개 ticker)
  2. v2 단기 신호 계산 (3M ±10%)
  3. 컨텍스트 알람 (KRE/SOXX/IWM)
  4. 장기 data.json fetch
  5. 충돌 신호 계산
  6. data_short.json + data_unified.json 생성
  7. Telegram 알림 (변경 시)

[통합 PWA: market-signal-pwa]
  data_unified.json fetch
  → 4탭 (메인/장기/단기/컨텍스트) 표시
```

## 📊 v2 단기 신호 정확도 (백테스트, 7,392일)

| 레벨 | n | 3M +10% 적중 | 3M -10% 적중 |
|---|---:|---:|---:|
| **PANIC_BUY** | 293 | **55.6%** ⭐ | 46.4% |
| **SHIFT_UP** | 689 | **48.9%** ⭐ | 16.5% |
| CAUTION_UP | 753 | 31.1% | 18.1% |
| NEUTRAL | 4,635 | 8.8% | 8.5% |
| CAUTION_DOWN | 877 | 11.5% | **31.8%** ⭐ |
| **SHIFT_DOWN** | 334 | 14.7% | **42.8%** ⭐ |

기저율: 3M +10% = 17.0%, 3M -10% = 15.8%

## 🚦 신호 4-Pillar

- **A. Price Momentum**: SPX 5d/20d, MA50 거리
- **B. Drawdown Depth**: SPX MA200 이탈
- **C. Credit & Rotation**: HYG 5d, XLP/XLY 20d
- **D. Macro Stress**: DXY, VIX 절대값, SKEW

## ⚠️ 컨텍스트 알람 (단독 정보, 행동 권고 X)

- **KRE 20d < -10%**: 은행 스트레스 (단독 -15% 적중 28%)
- **SOXX 20d < -10%**: 반도체 약세 (단독 -15% 적중 28%)
- **IWM/SPX 20d < -5%**: 시장 폭 약화 (단독 -15% 적중 26%)

## 🚀 설정

### 1. GitHub Secrets 설정

Repository Settings → Secrets and variables → Actions:

- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
- `TELEGRAM_CHAT_ID`: 채널 ID

(기존 장기 저장소와 동일 봇·채널 사용)

### 2. 저장소 Public 설정

Settings → General → Danger Zone → Change visibility → Public

(통합 PWA가 raw URL로 접근하려면 Public 필요)

### 3. GitHub Actions 활성화

Actions 탭 → "I understand my workflows, go ahead and enable them"

### 4. 첫 수동 실행

Actions → "v12 Short Signal Check" → Run workflow

성공 시 `data_short.json` 및 `data_unified.json` 생성됨.

## 🔗 통합 JSON URL

```
https://raw.githubusercontent.com/mryang82/market-signal-monitor-short/main/data_unified.json
```

PWA가 이 URL에서 데이터를 가져옵니다.

## 🛠️ 로컬 테스트

```bash
pip install -r requirements.txt
python auto_signal_short.py
```

`TELEGRAM_BOT_TOKEN`과 `TELEGRAM_CHAT_ID`는 환경변수로 설정 (없으면 알림만 생략).

## 📨 Telegram 알림 정책

- 단기 레벨 변경 시 즉시 알림
- 충돌 신호 (장기 매수 + 단기 매도 등) 발효 시 알림
- 변경 없으면 알림 없음 (조용)

## ⚙️ 운영 시간

| 시각 (KST) | 작업 |
|---|---|
| 07:17 | 장기 저장소 실행 (별도) |
| 07:30 | 단기 저장소 실행 (이 저장소) |
| 22:17 | 장기 저장소 실행 (별도) |
| 22:30 | 단기 저장소 실행 (이 저장소) |

## 🔍 백테스트 검증

8단계 검증을 거쳐 데이터로 입증된 신호만 활용:
- ✅ v8 매수 (장기 12M +15% 79.7% 적중)
- ✅ v2 단기 양방향 (위 표)
- ❌ v8 매도 (검증 실패, 운영에서 제외)
- ❌ NAAIM/F&G 매도 (정점에서 작동 안 함)

상세 백테스트 결과는 메인 PWA에서 확인.
