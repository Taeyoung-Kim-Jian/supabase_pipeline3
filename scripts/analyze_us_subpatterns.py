"""
US 주식 서브패턴 분석 및 AI 예측 스크립트
- B포인트 구간별 패턴 분석
- 유사 패턴 매칭 및 예측
- 투자 점수 계산
"""

import os
import sys
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from supabase import create_client
from dotenv import load_dotenv
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics.pairwise import cosine_similarity
import warnings
warnings.filterwarnings('ignore')

# 환경 변수 로드
load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_ANON_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print('❌ SUPABASE_URL 또는 SUPABASE_ANON_KEY가 설정되지 않았습니다.')
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

print('=' * 60)
print('🇺🇸 US 주식 서브패턴 분석 및 AI 예측 시작')
print('=' * 60)

# ============================================
# 1. 모든 종목 데이터 로드 (서브패턴 학습용)
# ============================================
print('\n📊 1단계: 종목 데이터 로드...')

# 모든 종목 조회 (비활성 포함 - 더 많은 서브패턴 학습)
stocks_result = supabase.table('us_stocks')\
    .select('종목코드, 종목명, 활성여부')\
    .execute()

if not stocks_result.data:
    print('❌ 종목이 없습니다.')
    sys.exit(1)

active_count = sum(1 for s in stocks_result.data if s.get('활성여부'))
print(f'✓ 전체 종목: {len(stocks_result.data)}개 (활성: {active_count}개, 비활성: {len(stocks_result.data) - active_count}개)')

# ============================================
# 2. 서브패턴 분석 함수
# ============================================
def extract_subpatterns(stock_code, stock_name):
    """
    특정 종목의 B포인트 구간별 서브패턴 추출
    """
    # B포인트 데이터 조회
    bt_result = supabase.table('us_bt_points')\
        .select('*')\
        .eq('종목코드', stock_code)\
        .order('순번', desc=False)\
        .execute()

    if not bt_result.data or len(bt_result.data) < 2:
        return []

    # 가격 데이터 조회 (최근 2년)
    two_years_ago = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
    prices_result = supabase.table('us_prices')\
        .select('날짜, 종가, 고가, 저가, pattern')\
        .eq('종목코드', stock_code)\
        .gte('날짜', two_years_ago)\
        .order('날짜', desc=False)\
        .execute()

    if not prices_result.data:
        return []

    # DataFrame 변환
    bt_df = pd.DataFrame(bt_result.data)
    prices_df = pd.DataFrame(prices_result.data)
    prices_df['날짜'] = pd.to_datetime(prices_df['날짜'])
    prices_df['종가'] = prices_df['종가'].astype(float)
    prices_df['고가'] = prices_df['고가'].astype(float)
    prices_df['저가'] = prices_df['저가'].astype(float)

    subpatterns = []

    # B포인트 구간별 분석 (연속된 B포인트 쌍)
    for i in range(len(bt_df) - 1):
        start_b = bt_df.iloc[i]
        end_b = bt_df.iloc[i + 1]

        start_date = pd.to_datetime(start_b['b날짜'])
        end_date = pd.to_datetime(end_b['b날짜'])
        start_price = float(start_b['b가격'])
        end_price = float(end_b['b가격'])

        # 해당 구간의 가격 데이터
        period_prices = prices_df[
            (prices_df['날짜'] >= start_date) &
            (prices_df['날짜'] <= end_date)
        ].copy()

        if len(period_prices) < 5:  # 최소 5일 이상
            continue

        # 수익률 계산
        period_prices['수익률'] = (period_prices['종가'] / start_price - 1) * 100

        기간 = len(period_prices)
        최고수익률 = period_prices['수익률'].max()
        최저수익률 = period_prices['수익률'].min()
        종료수익률 = (end_price / start_price - 1) * 100
        변동성 = period_prices['수익률'].std()

        # 메인 패턴 (기간 중 가장 많이 나타난 패턴)
        메인패턴 = period_prices['pattern'].mode()[0] if len(period_prices['pattern'].mode()) > 0 else '기타'

        # 정규화된 가격 데이터 (ML 학습용)
        scaler = MinMaxScaler()
        normalized_prices = scaler.fit_transform(period_prices[['종가']].values)
        정규화_가격 = normalized_prices.flatten().tolist()

        subpattern = {
            '종목코드': stock_code,
            '종목명': stock_name,
            '시작_b순번': int(start_b['순번']),
            '시작_b날짜': start_date.strftime('%Y-%m-%d'),
            '시작_b가격': start_price,
            '종료_b순번': int(end_b['순번']),
            '종료_b날짜': end_date.strftime('%Y-%m-%d'),
            '종료_b가격': end_price,
            '기간': 기간,
            '수익률': round(종료수익률, 2),
            '최고수익률': round(최고수익률, 2),
            '최저수익률': round(최저수익률, 2),
            '변동성': round(변동성, 2),
            '메인패턴': 메인패턴,
            '정규화_가격': 정규화_가격
        }

        subpatterns.append(subpattern)

    return subpatterns


# ============================================
# 3. 유사 패턴 매칭 및 예측 함수
# ============================================
def predict_pattern(stock_code, stock_name):
    """
    현재 진행 중인 B포인트 구간에 대한 예측
    """
    # 현재 B포인트 (가장 최근)
    current_bt = supabase.table('us_bt_points')\
        .select('*')\
        .eq('종목코드', stock_code)\
        .order('순번', desc=True)\
        .limit(1)\
        .execute()

    if not current_bt.data:
        return None

    current_b = current_bt.data[0]
    current_date = pd.to_datetime(current_b['b날짜'])
    current_price = float(current_b['b가격'])
    current_b_num = int(current_b['순번'])

    # 현재 가격 (가장 최근)
    latest_price_result = supabase.table('us_prices')\
        .select('날짜, 종가, pattern')\
        .eq('종목코드', stock_code)\
        .order('날짜', desc=True)\
        .limit(1)\
        .execute()

    if not latest_price_result.data:
        return None

    latest_price_data = latest_price_result.data[0]
    현재가 = float(latest_price_data['종가'])
    현재패턴 = latest_price_data['pattern']
    latest_date = pd.to_datetime(latest_price_data['날짜'])

    # 경과일수 및 현재 수익률
    현재_경과일수 = (latest_date - current_date).days
    현재_수익률 = round((현재가 / current_price - 1) * 100, 2)

    # 현재 구간의 가격 데이터
    current_period_prices = supabase.table('us_prices')\
        .select('날짜, 종가')\
        .eq('종목코드', stock_code)\
        .gte('날짜', current_date.strftime('%Y-%m-%d'))\
        .order('날짜', desc=False)\
        .execute()

    if not current_period_prices.data or len(current_period_prices.data) < 5:
        return None

    # 현재 패턴 정규화
    current_prices_df = pd.DataFrame(current_period_prices.data)
    current_prices_df['종가'] = current_prices_df['종가'].astype(float)
    scaler = MinMaxScaler()
    current_normalized = scaler.fit_transform(current_prices_df[['종가']].values).flatten()

    # 모든 서브패턴 조회 (유사 패턴 찾기)
    all_subpatterns = supabase.table('us_subpatterns')\
        .select('*')\
        .execute()

    if not all_subpatterns.data or len(all_subpatterns.data) < 10:
        return None

    # 유사도 계산
    similarities = []
    for sp in all_subpatterns.data:
        if not sp.get('정규화_가격'):
            continue

        sp_normalized = np.array(sp['정규화_가격'])

        # 길이 맞추기 (짧은 쪽에 맞춤)
        min_len = min(len(current_normalized), len(sp_normalized))
        if min_len < 5:
            continue

        curr_truncated = current_normalized[:min_len].reshape(1, -1)
        sp_truncated = sp_normalized[:min_len].reshape(1, -1)

        # 코사인 유사도
        sim = cosine_similarity(curr_truncated, sp_truncated)[0][0]

        if sim > 0.7:  # 유사도 70% 이상만
            similarities.append({
                'similarity': sim,
                'subpattern': sp
            })

    if len(similarities) < 3:
        return None

    # 유사도 높은 순으로 정렬
    similarities.sort(key=lambda x: x['similarity'], reverse=True)
    top_similar = similarities[:20]  # 상위 20개

    # 예상 수익률 계산
    expected_returns = [s['subpattern']['수익률'] for s in top_similar]
    max_returns = [s['subpattern']['최고수익률'] for s in top_similar]
    durations = [s['subpattern']['기간'] for s in top_similar]

    평균_예상수익률 = round(np.mean(expected_returns), 2)
    최소_예상수익률 = round(np.min(expected_returns), 2)
    최대_예상수익률 = round(np.max(expected_returns), 2)
    평균_최고수익률 = round(np.mean(max_returns), 2)
    평균_예상기간 = round(np.mean(durations))

    # 투자 점수 계산 (0-100) - 더 세밀한 차별화
    투자점수 = 0.0

    # 1. 예상 수익률 (40점) - 연속형 점수
    if 평균_예상수익률 >= 50:
        투자점수 += 40
    elif 평균_예상수익률 >= 40:
        투자점수 += 35 + (평균_예상수익률 - 40) * 0.5
    elif 평균_예상수익률 >= 30:
        투자점수 += 30 + (평균_예상수익률 - 30) * 0.5
    elif 평균_예상수익률 >= 20:
        투자점수 += 24 + (평균_예상수익률 - 20) * 0.6
    elif 평균_예상수익률 >= 10:
        투자점수 += 16 + (평균_예상수익률 - 10) * 0.8
    elif 평균_예상수익률 >= 5:
        투자점수 += 8 + (평균_예상수익률 - 5) * 1.6
    elif 평균_예상수익률 >= 0:
        투자점수 += 평균_예상수익률 * 1.6
    else:
        # 마이너스 수익률은 감점
        투자점수 += max(평균_예상수익률 * 2, -10)

    # 2. 신뢰도 (25점) - 유사 패턴 개수와 유사도
    평균_유사도 = np.mean([s['similarity'] for s in top_similar])
    유사패턴_점수 = min(len(top_similar) / 20 * 15, 15)  # 최대 15점
    유사도_점수 = (평균_유사도 - 0.7) / 0.3 * 10  # 0.7~1.0 → 0~10점
    투자점수 += 유사패턴_점수 + 유사도_점수

    # 3. 현재 패턴 (15점) - 패턴 강도
    if 현재패턴 == '돌파':
        투자점수 += 15
    elif 현재패턴 == '돌파눌림':
        투자점수 += 11
    elif 현재패턴 == '박스권':
        투자점수 += 7
    elif 현재패턴 == '기타':
        투자점수 += 3
    else:  # 이탈
        투자점수 += 0

    # 4. 현재 수익률 위치 (10점) - 진입 타이밍
    if 현재_수익률 < -10:
        투자점수 += 10
    elif 현재_수익률 < -5:
        투자점수 += 8 + (현재_수익률 + 10) * 0.4
    elif 현재_수익률 < 0:
        투자점수 += 5 + (현재_수익률 + 5) * 0.6
    elif 현재_수익률 < 5:
        투자점수 += 3 - 현재_수익률 * 0.4
    elif 현재_수익률 < 10:
        투자점수 += 1 - (현재_수익률 - 5) * 0.4
    else:
        # 이미 많이 올랐으면 감점
        투자점수 += max(0, 1 - (현재_수익률 - 10) * 0.5)

    # 5. 변동성 및 리스크 (10점) - 안정성 평가
    변동성_데이터 = [s['subpattern'].get('변동성', 0) for s in top_similar]
    평균_변동성 = np.mean(변동성_데이터)
    if 평균_변동성 < 5:
        투자점수 += 10
    elif 평균_변동성 < 10:
        투자점수 += 7 - (평균_변동성 - 5) * 0.6
    elif 평균_변동성 < 15:
        투자점수 += 4 - (평균_변동성 - 10) * 0.6
    else:
        투자점수 += max(0, 1 - (평균_변동성 - 15) * 0.2)

    # 최종 점수 (0-100 범위로 제한)
    투자점수 = round(max(0, min(투자점수, 100)), 1)
    신뢰도 = round(min(평균_유사도 * 100, 100), 1)

    # 매수가 추천 (현재가 기준 -2%, -4%, -6%, -8%, -10%)
    매수1 = round(현재가 * 0.98, 2)
    매수2 = round(현재가 * 0.96, 2)
    매수3 = round(현재가 * 0.94, 2)
    매수4 = round(현재가 * 0.92, 2)
    매수5 = round(현재가 * 0.90, 2)
    평균_매수가 = round((매수1 + 매수2 + 매수3 + 매수4 + 매수5) / 5, 2)

    # 목표가 (평균 예상 수익률 기준)
    목표가 = round(current_price * (1 + 평균_예상수익률 / 100), 2)
    목표_수익률 = round((목표가 / 현재가 - 1) * 100, 2)

    # 매수 추천 (더 엄격한 기준으로 집중 투자)
    if 투자점수 >= 80:
        매수추천 = '적극 매수'  # 상위 5% 이내
    elif 투자점수 >= 70:
        매수추천 = '매수'  # 상위 15% 이내
    elif 투자점수 >= 60:
        매수추천 = '관망'  # 상위 30% 이내
    elif 투자점수 >= 40:
        매수추천 = '보류'  # 중위권
    else:
        매수추천 = '비추천'  # 하위권

    # 유사 패턴 목록
    유사패턴_목록 = [
        {
            '종목코드': s['subpattern']['종목코드'],
            '종목명': s['subpattern']['종목명'],
            '유사도': round(s['similarity'] * 100, 2),
            '수익률': s['subpattern']['수익률'],
            '최고수익률': s['subpattern']['최고수익률'],
            '기간': s['subpattern']['기간']
        }
        for s in top_similar[:10]
    ]

    prediction = {
        '종목코드': stock_code,
        '종목명': stock_name,
        '현재_b순번': current_b_num,
        '현재_b날짜': current_date.strftime('%Y-%m-%d'),
        '현재_b가격': current_price,
        '현재_경과일수': 현재_경과일수,
        '현재_수익률': 현재_수익률,
        '현재가': 현재가,
        '유사패턴_개수': len(top_similar),
        '평균_예상수익률': 평균_예상수익률,
        '최소_예상수익률': 최소_예상수익률,
        '최대_예상수익률': 최대_예상수익률,
        '평균_최고수익률': 평균_최고수익률,
        '평균_예상기간': 평균_예상기간,
        '투자점수': 투자점수,
        '신뢰도': 신뢰도,
        '매수1': 매수1,
        '매수2': 매수2,
        '매수3': 매수3,
        '매수4': 매수4,
        '매수5': 매수5,
        '평균_매수가': 평균_매수가,
        '목표가': 목표가,
        '목표_수익률': 목표_수익률,
        '메인패턴': 현재패턴,
        '매수추천': 매수추천,
        '유사패턴_목록': 유사패턴_목록
    }

    return prediction


# ============================================
# 4. 메인 실행
# ============================================
print('\n📊 2단계: 서브패턴 추출 중...')

total_subpatterns = []
for stock in stocks_result.data:
    stock_code = stock['종목코드']
    stock_name = stock['종목명']

    subpatterns = extract_subpatterns(stock_code, stock_name)
    if subpatterns:
        total_subpatterns.extend(subpatterns)
        print(f'  ✓ {stock_name} ({stock_code}): {len(subpatterns)}개 서브패턴')

print(f'\n✓ 총 {len(total_subpatterns)}개 서브패턴 추출 완료')

# 기존 데이터 삭제 후 새로 삽입
if total_subpatterns:
    print('\n📊 3단계: 서브패턴 데이터 저장 중...')

    # 기존 데이터 삭제
    supabase.table('us_subpatterns').delete().neq('id', 0).execute()

    # 배치 삽입 (100개씩)
    batch_size = 100
    for i in range(0, len(total_subpatterns), batch_size):
        batch = total_subpatterns[i:i+batch_size]
        supabase.table('us_subpatterns').insert(batch).execute()
        print(f'  ✓ {i+len(batch)}/{len(total_subpatterns)} 저장됨')

    print(f'✓ 서브패턴 데이터 저장 완료')

# 예측 실행 (활성 종목만)
print('\n📊 4단계: AI 패턴 예측 중 (활성 종목만)...')

# 활성 종목만 필터링
active_stocks = [s for s in stocks_result.data if s.get('활성여부')]
print(f'  → 예측 대상: {len(active_stocks)}개 활성 종목')

predictions = []
for stock in active_stocks:
    stock_code = stock['종목코드']
    stock_name = stock['종목명']

    prediction = predict_pattern(stock_code, stock_name)
    if prediction:
        predictions.append(prediction)
        score = prediction["투자점수"]
        recommend = prediction["매수추천"]

        # 점수별 색상 표시
        if score >= 80:
            print(f'  🟢 {stock_name} ({stock_code}): {score}점, {recommend}')
        elif score >= 70:
            print(f'  🔵 {stock_name} ({stock_code}): {score}점, {recommend}')
        elif score >= 60:
            print(f'  🟡 {stock_name} ({stock_code}): {score}점, {recommend}')
        else:
            print(f'  ⚪ {stock_name} ({stock_code}): {score}점, {recommend}')

print(f'\n✓ 총 {len(predictions)}개 종목 예측 완료')

# 점수 분포 통계
if predictions:
    scores = [p['투자점수'] for p in predictions]
    print(f'\n📈 투자점수 분포:')
    print(f'  평균: {np.mean(scores):.1f}점')
    print(f'  최고: {np.max(scores):.1f}점')
    print(f'  최저: {np.min(scores):.1f}점')
    print(f'  80점 이상 (적극 매수): {sum(1 for s in scores if s >= 80)}개')
    print(f'  70~79점 (매수): {sum(1 for s in scores if 70 <= s < 80)}개')
    print(f'  60~69점 (관망): {sum(1 for s in scores if 60 <= s < 70)}개')
    print(f'  60점 미만: {sum(1 for s in scores if s < 60)}개')

# 예측 데이터 저장
if predictions:
    print('\n📊 5단계: 예측 데이터 저장 중...')

    # 기존 데이터 삭제
    supabase.table('us_pattern_predictions').delete().neq('id', 0).execute()

    # 배치 삽입
    batch_size = 50
    for i in range(0, len(predictions), batch_size):
        batch = predictions[i:i+batch_size]
        supabase.table('us_pattern_predictions').insert(batch).execute()
        print(f'  ✓ {i+len(batch)}/{len(predictions)} 저장됨')

    print(f'✓ 예측 데이터 저장 완료')

print('\n' + '=' * 60)
print('✅ US 주식 서브패턴 분석 및 AI 예측 완료')
print('=' * 60)
print(f'📊 서브패턴: {len(total_subpatterns)}개')
print(f'🎯 예측: {len(predictions)}개')
print('=' * 60)
