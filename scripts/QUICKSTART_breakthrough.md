# 신고가 돌파 전략 시스템 빠른 시작 가이드

## 🎯 목표
신규 돌파 종목에 대해 "즉시 진입 vs 조정 대기" 전략을 자동으로 추천받기

---

## ✅ 단계별 실행

### 1단계: 데이터베이스 테이블 생성 (5분)

1. **Supabase Dashboard 접속**
   - https://supabase.com/dashboard 로그인
   - 프로젝트 선택

2. **SQL Editor 실행**
   - 좌측 메뉴 → SQL Editor
   - New query 클릭

3. **SQL 스크립트 복사 & 실행**
   ```
   파일 위치: vercel_project/sql/13_create_breakthrough_recommendations_table.sql
   ```
   - 파일 내용 전체 복사
   - SQL Editor에 붙여넣기
   - "Run" 버튼 클릭
   - ✅ 성공 메시지 확인

4. **생성된 테이블 확인**
   - 좌측 메뉴 → Table Editor
   - `breakthrough_strategy_rules` 테이블 확인
   - `breakthrough_recommendations` 테이블 확인

---

### 2단계: 투자 규칙 학습 (10-20분)

1. **터미널 열기**
   ```bash
   cd "c:\Users\Lenovo\Desktop\주식 ml\swing\supabase_pipeline3\scripts"
   ```

2. **학습 스크립트 실행**
   ```bash
   python train_breakthrough_model.py
   ```

3. **실행 과정 확인**
   ```
   📊 돌파 데이터 로딩 중...
   ✓ 127개 종목의 돌파 데이터 로드 완료

   🔍 127개 종목 분석 시작...
   진행: 10개 케이스 처리 완료...
   진행: 20개 케이스 처리 완료...
   ...
   ✓ 총 85개 학습 데이터 생성 완료

   📊 전략 규칙 생성 중...
   ✓ 9개 규칙 생성 완료

   💾 규칙을 DB에 저장 중...
   ✓ 9개 규칙 저장 완료
   ```

4. **결과 파일 확인**
   ```
   analysis_results/
   ├── breakthrough_training_data_20250113_143022.csv
   └── breakthrough_rules_20250113_143022.json
   ```

5. **DB에서 규칙 확인**
   - Supabase Dashboard → Table Editor
   - `breakthrough_strategy_rules` 테이블 열기
   - 9개 규칙이 저장되어 있는지 확인

---

### 3단계: 신규 종목 추천 생성 (1-2분)

1. **추천 스크립트 실행**
   ```bash
   python recommend_breakthrough_strategy.py
   ```

2. **실행 결과 확인**
   ```
   📚 전략 규칙 로딩 중...
   ✓ 9개 규칙 로드 완료

   🔍 최근 30일 이내 돌파 종목 조회 중...
   ✓ 5개 최근 돌파 종목 발견

   분석 중: 삼성전자 (2025-01-15 돌파)
     ✓ 추천: 조정5% (신뢰도: 높음)
   ...

   📊 투자 전략 추천 결과
   ════════════════════════════════════════

   [1] 삼성전자 (005930)
   ────────────────────────────────────────
     돌파일: 2025-01-15 (3년 신고가 돌파)
     돌파가: 75,000원 → 현재가: 78,500원
     변동성: 3.2% (중간) | 고점도달: 8일 (보통)

     🎯 추천 전략: 조정5%
     💰 권장 진입가: 74,575원 (5% 조정 대기)
     📈 예상 수익률: 18.5% (승률 72.3%)
     🟢 신뢰도: 높음 (학습 샘플: 15개)
   ```

3. **결과 파일 확인**
   ```
   analysis_results/
   └── breakthrough_recommendations_20250113_144530.csv
   ```

4. **DB에서 추천 확인**
   - Supabase Dashboard → Table Editor
   - `breakthrough_recommendations` 테이블 열기
   - 추천 결과 확인

---

## 🔄 일상 운영

### 매일 또는 주기적 실행
```bash
# 최근 돌파 종목에 대한 추천 업데이트
python recommend_breakthrough_strategy.py
```

### 월 1회 재학습 (선택사항)
```bash
# 새로운 데이터로 규칙 재학습
python train_breakthrough_model.py
```

---

## 🌐 웹 대시보드 통합

### 추천 목록 표시
```javascript
// 최신 추천 5개
const { data } = await supabase
  .from('breakthrough_recommendations')
  .select('*')
  .order('생성일시', { ascending: false })
  .limit(5);

data.forEach(rec => {
  console.log(`${rec.종목명}: ${rec.추천전략} (${rec.신뢰도})`);
});
```

### 신뢰도 높은 추천만 필터링
```javascript
const { data } = await supabase
  .from('breakthrough_recommendations')
  .select('*')
  .in('신뢰도', ['높음', '보통'])
  .order('예상수익률', { ascending: false });
```

---

## 📊 결과 해석 가이드

### 신뢰도 등급
- 🟢 **높음**: 학습 샘플 10개 이상 → 믿고 따라도 됨
- 🟡 **보통**: 학습 샘플 5-9개 → 참고 자료로 활용
- 🟠 **낮음**: 학습 샘플 3-4개 → 신중히 판단
- ⚪ **규칙없음**: 해당 특성 조합 데이터 없음 → 기본 전략(즉시진입) 적용

### 추천 전략 의미
- **즉시진입**: 돌파 직후 바로 매수 (빠른 상승 예상)
- **조정5%**: 5% 하락 시 매수 (소폭 조정 후 재상승 예상)
- **조정10%**: 10% 하락 시 매수 (중간 조정 후 재상승 예상)
- **조정15%~20%**: 큰 조정 후 매수 (높은 변동성, 리스크 있지만 수익 기대)

### 투자 의사결정
```
예시 1) 신뢰도 높음 + 즉시진입
→ 바로 매수 고려

예시 2) 신뢰도 높음 + 조정10%
→ 10% 하락 시점까지 대기, 지정가 주문 설정

예시 3) 신뢰도 낮음
→ 다른 분석과 병행하여 신중히 판단
```

---

## ⚠️ 주의사항

1. **과거 성과 ≠ 미래 보장**
   - 추천은 과거 데이터 기반 통계적 예측입니다
   - 시장 상황 변화 시 적중률이 낮아질 수 있습니다

2. **신뢰도 확인 필수**
   - 신뢰도가 낮거나 "규칙없음"인 경우 주의
   - 샘플 수가 적으면 통계적 신뢰성이 낮습니다

3. **리스크 관리**
   - 추천만으로 투자하지 말고 다른 분석과 병행
   - 손절 라인 설정 필수
   - 포트폴리오 분산 투자 권장

4. **정기 재학습**
   - 시장 환경 변화 반영을 위해 월 1회 재학습 권장
   - 새로운 돌파 데이터가 쌓이면 규칙 정확도 향상

---

## 🛠️ 문제 해결

### "규칙 로드 실패" 에러
```bash
# 원인: 2단계(학습) 미실행
# 해결: train_breakthrough_model.py 먼저 실행
```

### "테이블이 없습니다" 에러
```bash
# 원인: 1단계(테이블 생성) 미실행
# 해결: 13_create_breakthrough_recommendations_table.sql 실행
```

### "추천할 종목이 없습니다"
```bash
# 원인: 최근 30일 이내 신규 돌파 종목 없음
# 해결: 정상 상황. 돌파 종목 발생 시 자동 추천됨
```

### 환경변수 오류
```bash
# 원인: .env 파일 설정 오류
# 해결: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY 확인
```

---

## 🚀 다음 단계

1. **웹 대시보드에 추천 섹션 추가**
   - breakthrough.html에 추천 탭 추가
   - 실시간 추천 표시

2. **알림 시스템 구축**
   - 신규 돌파 발생 시 자동 추천 생성
   - 권장 진입가 도달 시 알림

3. **성과 추적**
   - 추천대로 투자 시 수익률 기록
   - 규칙 정확도 모니터링

4. **자동화**
   - 매일 자동으로 추천 업데이트 (cron job)
   - 주간 성과 리포트 자동 생성

---

## 📞 도움이 필요하면

- README_breakthrough_strategy.md 전체 문서 참고
- 각 스크립트 상단 주석 확인
- 에러 메시지 캡처 후 문의

**완료! 이제 자동화된 돌파 전략 추천 시스템을 사용할 수 있습니다.** 🎉
