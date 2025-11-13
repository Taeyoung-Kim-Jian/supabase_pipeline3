# 신고가 돌파 투자 전략 분석 시스템

## 📋 개요

이 시스템은 과거 신고가 돌파 데이터를 학습하여, 신규 돌파 종목에 대한 최적 투자 전략을 자동으로 추천합니다.

**핵심 질문**: 신고가를 돌파한 종목에 즉시 진입할 것인가, 조정을 기다릴 것인가?

**답변 방법**: 과거 데이터를 분석하여 종목의 특성(변동성, 모멘텀 속도)에 따라 최적 전략을 학습하고 적용합니다.

---

## 🗂️ 시스템 구성

### 1️⃣ 분석 스크립트 (analyze_breakthrough_strategy.py)
**목적**: 과거 돌파 데이터를 분석하여 전략별 성과 비교

**분석 내용**:
- 즉시 진입 vs 조정 후 진입 (-5%, -10%, -15%, -20%) 수익률 비교
- 종목별 변동성, 고점 도달 속도, 조정 패턴 분석
- 전략별 승률과 평균 수익률 계산

**실행 방법**:
```bash
cd supabase_pipeline3/scripts
python analyze_breakthrough_strategy.py
```

**출력**:
- `analysis_results/breakthrough_strategy_analysis_YYYYMMDD_HHMMSS.csv`
- 각 종목별 전략 성과 상세 데이터

---

### 2️⃣ 학습 스크립트 (train_breakthrough_model.py)
**목적**: 과거 데이터로부터 투자 규칙 학습 및 저장

**학습 과정**:
1. `kr_breakthrough_history` 테이블에서 모든 돌파 데이터 로드
2. 각 돌파 건별로 180일간의 가격 데이터 분석
3. 종목 특성 계산:
   - **변동성**: 20일 기준 변동성 → 낮음(<2%), 중간(2-4%), 높음(>4%)
   - **속도**: 고점 도달 속도 → 빠름(<5일), 보통(5-15일), 느림(>15일)
4. 최적 전략 계산:
   - 즉시 진입 vs 조정 대기 (-5%, -10%, -15%, -20%) 비교
   - 각 전략의 최대 수익률 계산
5. 규칙 생성:
   - 변동성 × 속도 조합별로 그룹화 (총 9개 조합)
   - 각 그룹에서 가장 성과가 좋은 전략 선택
   - 평균 수익률, 승률 계산
6. DB 저장:
   - `breakthrough_strategy_rules` 테이블에 규칙 저장
   - 향후 실시간 추천에 활용

**실행 방법**:
```bash
cd supabase_pipeline3/scripts
python train_breakthrough_model.py
```

**출력**:
1. DB 테이블: `breakthrough_strategy_rules` (9개 규칙)
2. CSV: `analysis_results/breakthrough_training_data_YYYYMMDD_HHMMSS.csv`
3. JSON: `analysis_results/breakthrough_rules_YYYYMMDD_HHMMSS.json`

**예시 규칙**:
```
변동성: 낮음 | 속도: 빠름
  → 추천전략: 즉시진입
  → 평균 수익률: 15.3%
  → 승률: 78.5%
  → 샘플수: 12개

변동성: 높음 | 속도: 느림
  → 추천전략: 조정10%
  → 평균 수익률: 22.1%
  → 승률: 68.2%
  → 샘플수: 8개
```

---

### 3️⃣ 추천 스크립트 (recommend_breakthrough_strategy.py)
**목적**: 신규 돌파 종목에 대한 실시간 투자 전략 추천

**추천 과정**:
1. 최근 30일 이내 돌파 종목 조회
2. 각 종목의 특성 계산 (변동성, 속도)
3. DB에서 일치하는 규칙 검색
4. 구체적인 투자 추천 생성:
   - 추천 전략 (즉시진입 or 조정X% 대기)
   - 권장 진입가 계산
   - 예상 수익률 및 승률 제시
   - 신뢰도 평가 (학습 샘플 개수 기반)

**실행 방법**:
```bash
cd supabase_pipeline3/scripts
python recommend_breakthrough_strategy.py
```

**출력 예시**:
```
[1] 삼성전자 (005930)
──────────────────────────────────────────
  돌파일: 2025-01-15 (3년 신고가 돌파)
  돌파가: 75,000원 → 현재가: 78,500원
  변동성: 3.2% (중간) | 고점도달: 8일 (보통)

  🎯 추천 전략: 조정5%
  💰 권장 진입가: 74,575원 (5% 조정 대기)
  📈 예상 수익률: 18.5% (승률 72.3%)
  🟢 신뢰도: 높음 (학습 샘플: 15개)
```

**DB 저장**: `breakthrough_recommendations` 테이블에 추천 결과 저장

---

## 🗄️ 데이터베이스 구조

### breakthrough_strategy_rules (전략 규칙 테이블)
```sql
- 변동성구간: TEXT ('낮음', '중간', '높음')
- 속도구간: TEXT ('빠름', '보통', '느림')
- 추천전략: TEXT ('즉시진입', '조정5%', '조정10%', '조정15%', '조정20%')
- 평균수익률: NUMERIC(10,2)
- 승률: NUMERIC(5,2)
- 샘플수: INTEGER
- 생성일시: TIMESTAMP
```

### breakthrough_recommendations (추천 결과 테이블)
```sql
- 종목코드, 종목명
- 돌파일, 돌파가, 현재가, 돌파기간
- 변동성, 변동성구간
- 고점도달일, 속도구간
- 추천전략, 권장진입가, 대기여부
- 예상수익률, 전략승률
- 신뢰도 ('높음', '보통', '낮음', '규칙없음')
- 생성일시
```

---

## 🚀 실행 순서

### 초기 설정 (1회만 실행)
```bash
# 1. SQL 테이블 생성
# Supabase Dashboard → SQL Editor에서 실행:
vercel_project/sql/13_create_breakthrough_recommendations_table.sql

# 2. 규칙 학습 (과거 데이터 분석)
cd supabase_pipeline3/scripts
python train_breakthrough_model.py
```

### 일상 운영 (정기 실행)
```bash
# 신규 돌파 종목 추천 생성
python recommend_breakthrough_strategy.py

# 선택사항: 전체 분석 재실행
python analyze_breakthrough_strategy.py
```

---

## 📊 전략 분류 체계

### 변동성 구간
- **낮음**: < 2% (안정적 움직임)
- **중간**: 2% ~ 4% (보통 움직임)
- **높음**: > 4% (큰 변동성)

### 속도 구간
- **빠름**: < 5일 (빠른 상승)
- **보통**: 5 ~ 15일 (정상 상승)
- **느림**: > 15일 (느린 상승)

### 추천 전략
- **즉시진입**: 돌파 직후 바로 매수
- **조정5%**: 5% 하락 시 매수
- **조정10%**: 10% 하락 시 매수
- **조정15%**: 15% 하락 시 매수
- **조정20%**: 20% 하락 시 매수

---

## 🎯 활용 방법

### 1. 웹 대시보드 통합
`breakthrough_recommendations` 테이블을 조회하여 웹에서 표시:

```javascript
// 최신 추천 조회
const { data } = await supabase
  .from('breakthrough_recommendations')
  .select('*')
  .order('생성일시', { ascending: false })
  .limit(10);

// 신뢰도 높은 추천만 조회
const { data } = await supabase
  .from('breakthrough_recommendations')
  .select('*')
  .in('신뢰도', ['높음', '보통'])
  .order('예상수익률', { ascending: false });
```

### 2. 알림 시스템 구축
- 신규 돌파 종목 발생 시 추천 생성
- 신뢰도가 높은 추천에 대해 알림 발송
- 권장 진입가 도달 시 알림

### 3. 백테스팅 및 성과 평가
- 추천된 전략대로 투자했을 때의 성과 추적
- 규칙의 정확도 모니터링
- 주기적으로 재학습하여 규칙 업데이트

---

## ⚙️ 설정 및 커스터마이징

### 분석 기간 조정
```python
# recommend_breakthrough_strategy.py
recent_stocks = get_recent_breakthroughs(days=30)  # 30일 → 원하는 기간

# train_breakthrough_model.py
prices = get_price_data(stock_code, breakthrough_date, 180)  # 180일 → 원하는 기간
```

### 변동성/속도 구간 조정
```python
# train_breakthrough_model.py의 create_strategy_rules 함수
df['변동성구간'] = pd.cut(df['변동성'], bins=[0, 2, 4, 100], labels=['낮음', '중간', '높음'])
df['속도구간'] = pd.cut(df['고점도달일'], bins=[0, 5, 15, 999], labels=['빠름', '보통', '느림'])
```

### 조정 비율 추가/변경
```python
# calculate_best_strategy 함수
for correction_pct in [5, 10, 15, 20, 25]:  # 25% 추가
```

---

## 📈 기대 효과

1. **객관적 의사결정**: 감정이 아닌 데이터 기반 투자
2. **리스크 관리**: 종목 특성에 맞는 진입 타이밍 선택
3. **수익률 개선**: 과매수 시점 회피, 조정 기회 활용
4. **자동화**: 신규 종목 발생 시 즉시 추천 생성
5. **학습 개선**: 데이터 축적에 따라 규칙 정확도 향상

---

## 🔧 문제 해결

### 규칙이 생성되지 않음
```bash
# 원인: 학습 데이터 부족
# 해결: kr_breakthrough_history에 충분한 과거 데이터가 있는지 확인
```

### 추천 신뢰도가 낮음
```bash
# 원인: 해당 특성 조합의 샘플 수 부족
# 해결: 더 많은 과거 데이터 수집 또는 구간 조정
```

### DB 저장 실패
```bash
# 원인: 테이블이 생성되지 않음
# 해결: 13_create_breakthrough_recommendations_table.sql 실행
```

---

## 📝 라이선스 및 면책

이 시스템은 교육 및 연구 목적으로 제공됩니다.
실제 투자 결정은 본인의 판단과 책임하에 이루어져야 합니다.
과거 데이터 기반 예측이 미래 수익을 보장하지 않습니다.

---

## 📞 문의 및 개선 제안

시스템 개선 아이디어나 버그 발견 시 이슈 등록 또는 PR 환영합니다.
