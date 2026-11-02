# market-signal-monitor-short

**v14 단기·통합 저장소** — v2 단기 신호 + 나스닥100 -10% 첫 진입 + 추세 방어 모드(월말 10개월선) + 장기 v8 통합

## 시스템 구조

```
[장기: market-signal-monitor-auto]   평일 KST 07:17 / 07:47 / 22:17 (예약 시각)
  → data.json

[단기·통합: 이 저장소]                평일 KST 07:30 / 08:00 / 22:30 (예약 시각)
  1. yfinance fetch (17개 티커)
  2. v2 단기 신호 (SPX·VIX 등 4-Pillar)
  3. 나스닥100 52주 고점 대비 -10% 첫 진입 (★★)
  4. 추세 방어 모드: 월 마지막 거래일 종가 < 10개월선 → 주식 50%, 위 → 100%
  5. 장기 data.json 병합 (받은 값이 더 오래됐으면 이전 값 유지)
  6. data_short.json + data_unified.json (+ health)
  7. 텔레그램: 레벨 변경 · 나스닥 사건 · 방어 모드 전환 · 입력 결측 · v8 묵음 (전송 성공 시에만 기록 → 실패 시 재시도)

[PWA: market-signal-pwa] → data_unified.json 표시
```

GitHub 예약 실행은 실제로 아침 약 2시간, 저녁 4~6시간 늦게 돈다. 뉴욕 16:15 전이면 오늘 봉(장중 가격)을 버리고 전일 종가로 판정한다.

## 신호 등급 (v14, 사건 단위 검증)

| 신호 | 근거 | 운영 |
|---|---|---|
| 추세 방어 (S&P 500) | 1950~2026 연 11.5% / 최대 낙폭 -33% (보유 11.7% / -55%) | 핵심 — 월말에만 확정 |
| 추세 방어 (나스닥100) | 1986~2026 연 14.6% / -62% (보유 15.4% / -82%) | 강세장에선 연 2~3%p 비용 |
| 나스닥100 -10% 첫 진입 ★★ | 2011~ 21회 60일 +11.1% (기준선 +4.3%) · 1986~ 51회 +7.0% (+3.9%) | 큰 약세장 초입에선 실패 → 분할 매수 |
| v2 PANIC_BUY | 2011~ 사건 12회 중 9회 12M +15% (아무 날 46%) · 1990~ 26회 중 14회 (39%) | 2000~2010 약세장 11회 중 2회 |
| v2 CAUTION_DOWN / SHIFT_DOWN | 3개월 내 -10% 하락 경험 22.8% / 26.5% (평소 12.1%) | **낙폭 위험 경고 — 매도 권고 아님** |
| v2 SHIFT_UP / CAUTION_UP | 아무 날과 차이 작거나 없음 | 참고 |

운영 제외: 충돌 신호(장기+단기 조합), v8 매도 등급, 현금 비중 점수 규칙.
과거 문서의 일 단위 적중률 표(n=293 등)는 같은 위기를 반복 집계해 부풀린 수치라 삭제했다.

## 컨텍스트 알람 (참고 정보)

KRE 20일 < -10%, SOXX 20일 < -10%, IWM/SPX 20일 < -5%, VIX9D/VIX > 1.10 — 단독 효과는 검증되지 않았다.

## 설정

- Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- 저장소 Public (PWA가 raw URL로 읽음)
- 수동 실행: Actions → "v14 Short Signal Check" → Run workflow

통합 JSON: `https://raw.githubusercontent.com/mryang82/market-signal-monitor-short/main/data_unified.json`

## 로컬 실행

```bash
pip install -r requirements.txt
python auto_signal_short.py
```

텔레그램 환경변수가 없으면 알림은 생략된다(이때 알림 기록도 갱신되지 않음).
