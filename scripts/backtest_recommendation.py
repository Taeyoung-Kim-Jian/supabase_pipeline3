"""
추천 종목 전략 백테스팅 스크립트
- 신고가 돌파 후 조정 → 20일선 위 재상승 패턴 검증
- 과거 6개월 데이터로 전략 성공률 및 수익률 측정
- 최적 파라미터 도출
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from supabase import create_client, Client
import pandas as pd
import numpy as np

# Windows 콘솔 UTF-8 인코딩 설정
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

# .env 파일 로드
try:
    from dotenv import load_dotenv

    # 여러 경로에서 .env 찾기
    possible_paths = [
        Path(__file__).parent / '.env',  # scripts/.env
        Path(__file__).parent.parent / '.env',  # supabase_pipeline3/.env
        Path(__file__).parent.parent / 'scripts' / '.env',  # supabase_pipeline3/scripts/.env
    ]

    env_loaded = False
    for env_path in possible_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"✓ .env 파일 로드: {env_path}")
            env_loaded = True
            break

    if not env_loaded:
        print("⚠️  .env 파일을 찾을 수 없습니다. 환경변수를 직접 설정하세요.")
except ImportError:
    print("⚠️  python-dotenv가 설치되지 않았습니다. pip install python-dotenv")

# Supabase 클라이언트 초기화
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("\nERROR: Environment variables not set")
    print("\n필요한 환경변수:")
    print("  - SUPABASE_URL")
    print("  - SUPABASE_SERVICE_ROLE_KEY 또는 SUPABASE_ANON_KEY")
    print("\n해결 방법:")
    print("  1. scripts/.env 파일 생성")
    print("  2. vercel_project/scripts/.env 파일을 복사")
    print("  3. 또는 환경변수 직접 설정")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("=" * 80)
print("추천 전략 백테스팅 시작")
print(f"실행 시간(KST): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# 백테스팅 파라미터
BACKTEST_PARAMS = {
    'lookback_months': 6,  # 과거 6개월 데이터 분석
    'breakthrough_window': (30, 180),  # 신고가 돌파 후 30~180일
    'correction_range': (-25, -10),  # 고점 대비 -25% ~ -10% 조정
    'ma20_proximity': (0, 5),  # 20일선 대비 0~5% 이내
    'holding_period': 60,  # 추천 후 60일 수익률 측정
    'min_investment_score': 70,  # 최소 투자점수
}

def get_all_stocks():
    """전체 종목 리스트 조회"""
    try:
        response = supabase.table('stocks').select('종목코드, 종목명').execute()
        return response.data or []
    except Exception as e:
        print(f"ERROR: {e}")
        return []

def get_breakthrough_history(stock_code, start_date):
    """신고가 돌파 이력 조회 (kr_breakthrough_history 테이블)"""
    try:
        # kr_breakthrough_history 테이블에서 데이터 조회
        response = supabase.table('kr_breakthrough_history').select('*').eq('종목코드', stock_code).execute()

        if not response.data or len(response.data) == 0:
            return []

        breakthroughs = []
        for row in response.data:
            # 돌파일_1년 ~ 돌파일_5년 확인
            for period in ['1년', '2년', '3년', '4년', '5년']:
                col_name = f'돌파일_{period}'
                if col_name in row and row[col_name]:
                    breakthrough_date = row[col_name]
                    if isinstance(breakthrough_date, str):
                        breakthrough_date = breakthrough_date.split('T')[0]

                    if breakthrough_date >= start_date:
                        breakthroughs.append({
                            '종목코드': stock_code,
                            '돌파일': breakthrough_date,
                            '기간': period,
                            '강도': {'5년': 5, '4년': 4, '3년': 3, '2년': 2, '1년': 1}[period]
                        })

        return breakthroughs
    except Exception as e:
        return []

def get_price_history(stock_code, start_date, end_date):
    """가격 히스토리 조회"""
    try:
        response = supabase.table('prices').select('날짜, 시가, 고가, 저가, 종가, 거래량, pattern').eq('종목코드', stock_code).gte('날짜', start_date).lte('날짜', end_date).order('날짜', desc=False).execute()
        return response.data or []
    except:
        return []

def calculate_ma20(prices_df, date):
    """특정 날짜의 20일 이동평균 계산"""
    if len(prices_df) < 20:
        return None

    date_idx = prices_df[prices_df['날짜'] == date].index
    if len(date_idx) == 0:
        return None

    idx = date_idx[0]
    if idx < 19:
        return None

    ma20 = prices_df.iloc[idx-19:idx+1]['종가'].mean()
    return ma20

def calculate_ma20_slope(prices_df, date):
    """20일선 기울기 계산 (5일 전 대비)"""
    if len(prices_df) < 25:
        return None

    date_idx = prices_df[prices_df['날짜'] == date].index
    if len(date_idx) == 0:
        return None

    idx = date_idx[0]
    if idx < 24:
        return None

    ma20_today = prices_df.iloc[idx-19:idx+1]['종가'].mean()
    ma20_5days_ago = prices_df.iloc[idx-24:idx-4]['종가'].mean()

    if ma20_5days_ago == 0:
        return None

    slope = (ma20_today - ma20_5days_ago) / ma20_5days_ago * 100
    return slope

def get_peak_after_breakthrough(prices_df, breakthrough_date):
    """돌파 이후 최고가 계산"""
    prices_after = prices_df[prices_df['날짜'] > breakthrough_date]
    if len(prices_after) == 0:
        return None, None

    peak_row = prices_after.loc[prices_after['고가'].idxmax()]
    return peak_row['고가'], peak_row['날짜']

def calculate_future_return(prices_df, entry_date, holding_days):
    """추천 후 수익률 계산"""
    entry_idx = prices_df[prices_df['날짜'] == entry_date].index
    if len(entry_idx) == 0:
        return None

    entry_idx = entry_idx[0]
    entry_price = prices_df.iloc[entry_idx]['종가']

    exit_idx = min(entry_idx + holding_days, len(prices_df) - 1)
    exit_price = prices_df.iloc[exit_idx]['종가']

    return_pct = (exit_price - entry_price) / entry_price * 100

    # 중간 최고가/최저가도 계산
    slice_df = prices_df.iloc[entry_idx:exit_idx+1]
    max_price = slice_df['고가'].max()
    min_price = slice_df['저가'].min()

    max_return = (max_price - entry_price) / entry_price * 100
    max_drawdown = (min_price - entry_price) / entry_price * 100

    return {
        'return': return_pct,
        'max_return': max_return,
        'max_drawdown': max_drawdown,
        'entry_price': entry_price,
        'exit_price': exit_price
    }

def check_recommendation_criteria(prices_df, check_date, breakthrough_info, params):
    """추천 조건 체크"""

    # 1. 돌파일로부터 경과일수 체크
    breakthrough_date = breakthrough_info['돌파일']
    days_since_breakthrough = (datetime.strptime(check_date, '%Y-%m-%d') - datetime.strptime(breakthrough_date, '%Y-%m-%d')).days

    if days_since_breakthrough < params['breakthrough_window'][0] or days_since_breakthrough > params['breakthrough_window'][1]:
        return False, "돌파 후 기간 미달"

    # 2. 돌파 후 고점 계산
    peak_price, peak_date = get_peak_after_breakthrough(prices_df, breakthrough_date)
    if peak_price is None:
        return False, "고점 없음"

    # 3. 현재가 조회
    current_row = prices_df[prices_df['날짜'] == check_date]
    if len(current_row) == 0:
        return False, "가격 데이터 없음"

    current_price = current_row.iloc[0]['종가']

    # 4. 고점 대비 조정률 체크
    correction_pct = (current_price - peak_price) / peak_price * 100
    if correction_pct < params['correction_range'][0] or correction_pct > params['correction_range'][1]:
        return False, f"조정률 부적합 ({correction_pct:.1f}%)"

    # 5. 20일 이동평균선 체크
    ma20 = calculate_ma20(prices_df, check_date)
    if ma20 is None:
        return False, "MA20 계산 불가"

    if current_price < ma20:
        return False, "20일선 아래"

    # 6. 20일선 근접도 체크
    ma20_proximity = (current_price - ma20) / ma20 * 100
    if ma20_proximity < params['ma20_proximity'][0] or ma20_proximity > params['ma20_proximity'][1]:
        return False, f"20일선 거리 부적합 ({ma20_proximity:.1f}%)"

    # 7. 20일선 기울기 체크 (상승 중)
    ma20_slope = calculate_ma20_slope(prices_df, check_date)
    if ma20_slope is None or ma20_slope < 0:
        return False, "20일선 하락 중"

    # 8. 패턴 체크 (박스권 또는 돌파눌림)
    current_pattern = current_row.iloc[0].get('pattern', '')
    if current_pattern not in ['박스권', '돌파눌림']:
        return False, f"패턴 부적합 ({current_pattern})"

    return True, {
        'days_since_breakthrough': days_since_breakthrough,
        'correction_pct': correction_pct,
        'ma20_proximity': ma20_proximity,
        'ma20_slope': ma20_slope,
        'pattern': current_pattern,
        'peak_price': peak_price,
        'current_price': current_price
    }

def backtest_single_stock(stock_code, stock_name, start_date, end_date):
    """개별 종목 백테스팅"""

    # 1. 신고가 돌파 이력 조회
    breakthroughs = get_breakthrough_history(stock_code, start_date)
    if len(breakthroughs) == 0:
        return []

    # 2. 가격 히스토리 조회 (더 넓은 범위)
    extended_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d')
    prices = get_price_history(stock_code, extended_start, end_date)
    if len(prices) < 50:
        return []

    prices_df = pd.DataFrame(prices)

    # 3. 각 돌파 이벤트에 대해 백테스팅
    results = []
    for bt in breakthroughs:
        breakthrough_date = bt['돌파일']

        # 돌파 후 30일부터 180일까지 매일 체크
        check_start = datetime.strptime(breakthrough_date, '%Y-%m-%d') + timedelta(days=BACKTEST_PARAMS['breakthrough_window'][0])
        check_end = datetime.strptime(breakthrough_date, '%Y-%m-%d') + timedelta(days=BACKTEST_PARAMS['breakthrough_window'][1])

        check_date = check_start
        already_recommended = False

        while check_date <= check_end and check_date <= datetime.strptime(end_date, '%Y-%m-%d'):
            check_date_str = check_date.strftime('%Y-%m-%d')

            # 추천 조건 체크
            passed, result = check_recommendation_criteria(prices_df, check_date_str, bt, BACKTEST_PARAMS)

            if passed and not already_recommended:
                # 추천 성공 - 향후 수익률 계산
                future_return = calculate_future_return(prices_df, check_date_str, BACKTEST_PARAMS['holding_period'])

                if future_return:
                    results.append({
                        '종목코드': stock_code,
                        '종목명': stock_name,
                        '돌파일': breakthrough_date,
                        '돌파기간': bt['기간'],
                        '돌파강도': bt['강도'],
                        '추천일': check_date_str,
                        '경과일수': result['days_since_breakthrough'],
                        '조정률': result['correction_pct'],
                        'MA20근접도': result['ma20_proximity'],
                        'MA20기울기': result['ma20_slope'],
                        '패턴': result['pattern'],
                        '진입가': future_return['entry_price'],
                        '청산가': future_return['exit_price'],
                        '수익률': future_return['return'],
                        '최대수익률': future_return['max_return'],
                        '최대낙폭': future_return['max_drawdown'],
                    })
                    already_recommended = True

            check_date += timedelta(days=1)

    return results

def run_backtest():
    """전체 백테스팅 실행"""

    # 백테스트 기간 설정
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=BACKTEST_PARAMS['lookback_months'] * 30)).strftime('%Y-%m-%d')

    print(f"\n백테스트 기간: {start_date} ~ {end_date}")
    print(f"파라미터:")
    for key, value in BACKTEST_PARAMS.items():
        print(f"  - {key}: {value}")
    print("\n")

    # 전체 종목 조회
    stocks = get_all_stocks()
    print(f"총 {len(stocks)}개 종목 백테스팅 시작...\n")

    all_results = []
    processed = 0

    for stock in stocks:
        stock_code = stock['종목코드']
        stock_name = stock['종목명']

        results = backtest_single_stock(stock_code, stock_name, start_date, end_date)
        all_results.extend(results)

        processed += 1
        if processed % 50 == 0:
            print(f"진행: {processed}/{len(stocks)} 종목 완료")

    print(f"\n백테스팅 완료: 총 {len(all_results)}개 추천 신호 발견\n")

    # 결과 분석
    if len(all_results) > 0:
        df = pd.DataFrame(all_results)

        print("=" * 80)
        print("백테스팅 결과 분석")
        print("=" * 80)

        # 전체 통계
        print(f"\n[전체 통계]")
        print(f"총 추천 횟수: {len(df)}")
        print(f"평균 수익률: {df['수익률'].mean():.2f}%")
        print(f"중간 수익률: {df['수익률'].median():.2f}%")
        print(f"승률: {(df['수익률'] > 0).sum() / len(df) * 100:.1f}%")
        print(f"최대 수익: {df['수익률'].max():.2f}%")
        print(f"최대 손실: {df['수익률'].min():.2f}%")
        print(f"평균 최대낙폭: {df['최대낙폭'].mean():.2f}%")

        # 돌파 기간별 분석
        print(f"\n[돌파 기간별 분석]")
        for period in ['1년', '2년', '3년', '4년', '5년']:
            subset = df[df['돌파기간'] == period]
            if len(subset) > 0:
                print(f"\n{period} 신고가 돌파:")
                print(f"  - 추천 횟수: {len(subset)}")
                print(f"  - 평균 수익률: {subset['수익률'].mean():.2f}%")
                print(f"  - 승률: {(subset['수익률'] > 0).sum() / len(subset) * 100:.1f}%")

        # 패턴별 분석
        print(f"\n[패턴별 분석]")
        for pattern in df['패턴'].unique():
            subset = df[df['패턴'] == pattern]
            print(f"\n{pattern}:")
            print(f"  - 추천 횟수: {len(subset)}")
            print(f"  - 평균 수익률: {subset['수익률'].mean():.2f}%")
            print(f"  - 승률: {(subset['수익률'] > 0).sum() / len(subset) * 100:.1f}%")

        # 상위 10개 종목
        print(f"\n[수익률 상위 10개 추천]")
        top10 = df.nlargest(10, '수익률')[['종목명', '추천일', '돌파기간', '패턴', '수익률']]
        print(top10.to_string(index=False))

        # 하위 10개 종목
        print(f"\n[수익률 하위 10개 추천]")
        bottom10 = df.nsmallest(10, '수익률')[['종목명', '추천일', '돌파기간', '패턴', '수익률']]
        print(bottom10.to_string(index=False))

        # 결과를 CSV로 저장
        output_file = Path(__file__).parent.parent / 'backtest_results.csv'
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n상세 결과 저장: {output_file}")

        return df
    else:
        print("추천 신호를 찾지 못했습니다.")
        return None

if __name__ == "__main__":
    try:
        results = run_backtest()
        print("\n백테스팅 완료!")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
