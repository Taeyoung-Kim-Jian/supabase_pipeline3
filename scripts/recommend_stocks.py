"""
일일 추천 종목 선정 스크립트
- 백테스팅 결과 기반 검증된 전략 적용
- 신고가 돌파 후 조정 → 20일선 위 재상승 준비 종목 선정
- 매일 상위 5개 종목 추천
- recommended_stocks 테이블에 저장
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from supabase import create_client, Client
import pandas as pd

# .env 파일 로드
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except:
    pass

# Supabase 클라이언트 초기화
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Environment variables not set")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("=" * 80)
print("일일 추천 종목 선정 시작")
print(f"실행 시간(KST): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# 추천 기준 파라미터 (백테스팅으로 검증된 최적값)
RECOMMENDATION_PARAMS = {
    'breakthrough_window': (30, 180),  # 신고가 돌파 후 30~180일
    'correction_range': (-25, -10),  # 고점 대비 -25% ~ -10% 조정
    'ma20_proximity': (0, 5),  # 20일선 대비 0~5% 이내
    'min_investment_score': 70,  # 최소 투자점수
    'min_breakthrough_period': 2,  # 최소 돌파 기간 (1=1년, 2=2년, ...)
    'preferred_patterns': ['박스권', '돌파눌림'],  # 선호 패턴
    'max_recommendations': 5,  # 최대 추천 개수
}

def get_all_stocks():
    """전체 종목 리스트 조회"""
    try:
        response = supabase.table('stocks').select('종목코드, 종목명').execute()
        return response.data or []
    except Exception as e:
        print(f"ERROR: {e}")
        return []

def get_recent_breakthrough(stock_code):
    """최근 신고가 돌파 정보 조회"""
    try:
        response = supabase.table('breakthrough').select('*').eq('종목코드', stock_code).execute()

        if not response.data or len(response.data) == 0:
            return None

        row = response.data[0]
        breakthroughs = []

        # 돌파일_1년 ~ 돌파일_5년 확인
        for period in ['5년', '4년', '3년', '2년', '1년']:
            col_name = f'돌파일_{period}'
            if col_name in row and row[col_name]:
                breakthrough_date = row[col_name]
                if isinstance(breakthrough_date, str):
                    breakthrough_date = breakthrough_date.split('T')[0]

                days_ago = (datetime.now() - datetime.strptime(breakthrough_date, '%Y-%m-%d')).days

                # 30~180일 이내 돌파만 고려
                if RECOMMENDATION_PARAMS['breakthrough_window'][0] <= days_ago <= RECOMMENDATION_PARAMS['breakthrough_window'][1]:
                    breakthroughs.append({
                        '돌파일': breakthrough_date,
                        '기간': period,
                        '강도': {'5년': 5, '4년': 4, '3년': 3, '2년': 2, '1년': 1}[period],
                        '경과일수': days_ago
                    })

        # 가장 강한 돌파 반환
        if breakthroughs:
            return sorted(breakthroughs, key=lambda x: x['강도'], reverse=True)[0]

        return None
    except:
        return None

def get_recent_prices(stock_code, days=60):
    """최근 N일 가격 데이터 조회"""
    try:
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        response = supabase.table('prices').select('날짜, 시가, 고가, 저가, 종가, 거래량, pattern').eq('종목코드', stock_code).gte('날짜', date_from).order('날짜', desc=False).execute()
        return response.data or []
    except:
        return []

def get_current_pattern_and_score(stock_code):
    """현재 패턴 및 투자점수 조회"""
    try:
        response = supabase.table('pattern_predictions').select('메인패턴, 투자점수').eq('종목코드', stock_code).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except:
        return None

def calculate_ma20(prices_df):
    """20일 이동평균선 계산"""
    if len(prices_df) < 20:
        return None, None

    ma20 = prices_df.tail(20)['종가'].mean()
    ma20_5days_ago = prices_df.tail(25).head(20)['종가'].mean() if len(prices_df) >= 25 else None

    slope = None
    if ma20_5days_ago and ma20_5days_ago > 0:
        slope = (ma20 - ma20_5days_ago) / ma20_5days_ago * 100

    return ma20, slope

def get_peak_after_breakthrough(prices_df, breakthrough_date):
    """돌파 이후 최고가 계산"""
    prices_after = prices_df[prices_df['날짜'] > breakthrough_date]
    if len(prices_after) == 0:
        return None

    return prices_after['고가'].max()

def calculate_recent_volatility(prices_df, days=10):
    """최근 N일 변동성 계산"""
    if len(prices_df) < days:
        return None

    recent_prices = prices_df.tail(days)
    daily_returns = recent_prices['종가'].pct_change().dropna()

    if len(daily_returns) == 0:
        return None

    return daily_returns.std() * 100

def check_recommendation_criteria(stock_code, stock_name):
    """추천 조건 체크"""

    # 1. 신고가 돌파 이력 확인
    breakthrough = get_recent_breakthrough(stock_code)
    if not breakthrough:
        return None

    # 최소 돌파 기간 체크
    if breakthrough['강도'] < RECOMMENDATION_PARAMS['min_breakthrough_period']:
        return None

    # 2. 가격 데이터 조회
    prices = get_recent_prices(stock_code, 60)
    if len(prices) < 30:
        return None

    prices_df = pd.DataFrame(prices)
    current_price = prices_df.iloc[-1]['종가']
    current_date = prices_df.iloc[-1]['날짜']

    # 3. 돌파 후 고점 계산
    peak_price = get_peak_after_breakthrough(prices_df, breakthrough['돌파일'])
    if not peak_price:
        return None

    # 4. 고점 대비 조정률 체크
    correction_pct = (current_price - peak_price) / peak_price * 100
    if correction_pct < RECOMMENDATION_PARAMS['correction_range'][0] or correction_pct > RECOMMENDATION_PARAMS['correction_range'][1]:
        return None

    # 5. 20일 이동평균선 체크
    ma20, ma20_slope = calculate_ma20(prices_df)
    if not ma20:
        return None

    # 20일선 위에 있는지
    if current_price < ma20:
        return None

    # 20일선 근접도
    ma20_proximity = (current_price - ma20) / ma20 * 100
    if ma20_proximity < RECOMMENDATION_PARAMS['ma20_proximity'][0] or ma20_proximity > RECOMMENDATION_PARAMS['ma20_proximity'][1]:
        return None

    # 20일선 상승 중인지
    if not ma20_slope or ma20_slope < 0:
        return None

    # 6. 패턴 체크
    pattern_data = get_current_pattern_and_score(stock_code)
    if not pattern_data:
        return None

    current_pattern = pattern_data.get('메인패턴', '')
    investment_score = pattern_data.get('투자점수', 0)

    if current_pattern not in RECOMMENDATION_PARAMS['preferred_patterns']:
        return None

    # 7. 투자점수 체크
    if investment_score < RECOMMENDATION_PARAMS['min_investment_score']:
        return None

    # 8. 최근 변동성 체크 (횡보 확인)
    volatility = calculate_recent_volatility(prices_df, 10)

    # 9. 전고점까지 거리 계산
    distance_to_peak = (peak_price - current_price) / current_price * 100

    # 10. 종합 점수 계산
    score = 0

    # 돌파 강도 (최대 30점)
    score += breakthrough['강도'] * 6

    # 조정 적정성 (최대 20점) - 15~20% 조정이 이상적
    ideal_correction = -17.5
    correction_score = 20 - abs(correction_pct - ideal_correction) * 2
    score += max(0, min(20, correction_score))

    # 20일선 밀착도 (최대 20점) - 0~3% 이내가 이상적
    proximity_score = 20 - ma20_proximity * 5
    score += max(0, min(20, proximity_score))

    # 전고점 근접성 (최대 15점) - 15~20% 거리가 이상적
    ideal_distance = 17.5
    distance_score = 15 - abs(distance_to_peak - ideal_distance) * 1.5
    score += max(0, min(15, distance_score))

    # 투자점수 (최대 10점)
    score += (investment_score - 70) / 30 * 10

    # 변동성 (최대 5점) - 낮을수록 좋음
    if volatility:
        volatility_score = 5 - min(volatility, 5)
        score += max(0, volatility_score)

    return {
        '종목코드': stock_code,
        '종목명': stock_name,
        '돌파일': breakthrough['돌파일'],
        '돌파기간': breakthrough['기간'],
        '돌파강도': breakthrough['강도'],
        '경과일수': breakthrough['경과일수'],
        '현재가': current_price,
        '고점가격': peak_price,
        '조정률': round(correction_pct, 2),
        'MA20': round(ma20, 0),
        'MA20근접도': round(ma20_proximity, 2),
        'MA20기울기': round(ma20_slope, 2),
        '패턴': current_pattern,
        '투자점수': investment_score,
        '전고점거리': round(distance_to_peak, 2),
        '최근변동성': round(volatility, 2) if volatility else 0,
        '종합점수': round(score, 2),
        '추천일': datetime.now().strftime('%Y-%m-%d'),
    }

def save_recommendations(recommendations):
    """추천 종목을 DB에 저장"""
    try:
        # 기존 오늘 추천 삭제
        today = datetime.now().strftime('%Y-%m-%d')
        supabase.table('recommended_stocks').delete().eq('추천일', today).execute()

        # 새 추천 저장
        for idx, rec in enumerate(recommendations, 1):
            rec['순위'] = idx
            supabase.table('recommended_stocks').insert(rec).execute()

        print(f"✓ {len(recommendations)}개 추천 종목 저장 완료")
        return True
    except Exception as e:
        print(f"ERROR saving recommendations: {e}")
        return False

def generate_recommendations():
    """추천 종목 생성"""

    # 전체 종목 조회
    stocks = get_all_stocks()
    print(f"총 {len(stocks)}개 종목 분석 시작...\n")

    candidates = []
    processed = 0

    for stock in stocks:
        stock_code = stock['종목코드']
        stock_name = stock['종목명']

        result = check_recommendation_criteria(stock_code, stock_name)
        if result:
            candidates.append(result)

        processed += 1
        if processed % 100 == 0:
            print(f"진행: {processed}/{len(stocks)} 종목 완료")

    print(f"\n후보 종목: {len(candidates)}개 발견\n")

    if len(candidates) == 0:
        print("추천 조건을 만족하는 종목이 없습니다.")
        return []

    # 종합점수 기준 정렬
    candidates_df = pd.DataFrame(candidates)
    candidates_df = candidates_df.sort_values('종합점수', ascending=False)

    # 상위 N개 선택
    top_recommendations = candidates_df.head(RECOMMENDATION_PARAMS['max_recommendations']).to_dict('records')

    # 결과 출력
    print("=" * 80)
    print(f"오늘의 추천 종목 TOP {len(top_recommendations)}")
    print("=" * 80)

    for idx, rec in enumerate(top_recommendations, 1):
        print(f"\n[{idx}위] {rec['종목명']} ({rec['종목코드']})")
        print(f"  - 종합점수: {rec['종합점수']}")
        print(f"  - 돌파: {rec['돌파기간']} 신고가 ({rec['돌파일']}, {rec['경과일수']}일 경과)")
        print(f"  - 현재가: {rec['현재가']:,}원 (고점 대비 {rec['조정률']}%)")
        print(f"  - 20일선: {rec['MA20']:,}원 (근접도 +{rec['MA20근접도']}%, 기울기 +{rec['MA20기울기']}%)")
        print(f"  - 패턴: {rec['패턴']} (투자점수 {rec['투자점수']})")
        print(f"  - 전고점까지: +{rec['전고점거리']}%")

    return top_recommendations

if __name__ == "__main__":
    try:
        recommendations = generate_recommendations()

        if recommendations:
            save_recommendations(recommendations)
            print("\n✓ 추천 종목 선정 완료!")
        else:
            print("\n추천 가능한 종목이 없습니다.")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
