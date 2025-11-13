"""
신고가 돌파 투자 전략 분석 스크립트
- 종목별 특성에 따른 최적 진입 전략 도출
- 돌파 즉시 진입 vs 조정 후 진입 비교
- 기간별, 변동성별, 시가총액별 분석
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from supabase import create_client, Client
import pandas as pd
import numpy as np
from collections import defaultdict

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
    possible_paths = [
        Path(__file__).parent / '.env',
        Path(__file__).parent.parent / '.env',
        Path(__file__).parent.parent / 'scripts' / '.env',
    ]
    env_loaded = False
    for env_path in possible_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"✓ .env 파일 로드: {env_path}")
            env_loaded = True
            break
    if not env_loaded:
        print("⚠️  .env 파일을 찾을 수 없습니다.")
except ImportError:
    print("⚠️  python-dotenv가 설치되지 않았습니다.")

# Supabase 클라이언트 초기화
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("\nERROR: Environment variables not set")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("=" * 80)
print("신고가 돌파 투자 전략 분석")
print(f"실행 시간(KST): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)


def get_breakthrough_data():
    """신고가 돌파 데이터 조회"""
    print("\n📊 돌파 데이터 로딩 중...")
    try:
        response = supabase.table('kr_breakthrough_history').select('*').execute()
        if response.data:
            print(f"✓ {len(response.data)}개 종목의 돌파 데이터 로드 완료")
            return response.data
        return []
    except Exception as e:
        print(f"ERROR: {e}")
        return []


def get_price_data(stock_code, start_date):
    """특정 종목의 가격 데이터 조회"""
    try:
        response = supabase.table('prices').select('*').eq('종목코드', stock_code).gte('날짜', start_date).order('날짜', desc=False).execute()
        return response.data or []
    except:
        return []


def calculate_volatility(prices_df, days=20):
    """변동성 계산"""
    if len(prices_df) < days:
        return None
    recent = prices_df.tail(days)
    daily_returns = recent['종가'].pct_change().dropna()
    if len(daily_returns) == 0:
        return None
    return daily_returns.std() * 100


def analyze_entry_strategy(stock_code, stock_name, breakthrough_date, breakthrough_price, prices_after_breakthrough):
    """
    진입 전략 분석
    - 즉시 진입: 돌파일 다음날 시가 진입
    - 조정 후 진입: 고점 대비 -5%, -10%, -15%, -20% 조정 후 진입
    """
    if len(prices_after_breakthrough) < 5:
        return None

    df = pd.DataFrame(prices_after_breakthrough)
    df['날짜'] = pd.to_datetime(df['날짜'])
    df = df.sort_values('날짜')

    # 돌파 후 최고가/최저가
    peak_price = df['고가'].max()
    lowest_price = df['저가'].min()

    # 최고가/최저가 도달 시점
    peak_date = df[df['고가'] == peak_price]['날짜'].iloc[0]
    lowest_date = df[df['저가'] == lowest_price]['날짜'].iloc[0]

    # 돌파일로부터 경과일
    peak_days = (peak_date - pd.to_datetime(breakthrough_date)).days
    lowest_days = (lowest_date - pd.to_datetime(breakthrough_date)).days

    # 전략 1: 즉시 진입 (돌파일 다음날)
    if len(df) > 0:
        entry_price_immediate = df.iloc[0]['시가']
        immediate_max_return = (peak_price - entry_price_immediate) / entry_price_immediate * 100
        immediate_min_return = (lowest_price - entry_price_immediate) / entry_price_immediate * 100
    else:
        entry_price_immediate = breakthrough_price
        immediate_max_return = 0
        immediate_min_return = 0

    # 전략 2-5: 조정 후 진입
    correction_strategies = {}
    for correction_pct in [5, 10, 15, 20]:
        target_price = peak_price * (1 - correction_pct / 100)

        # 목표 조정가에 도달했는지 확인
        reached = df[df['저가'] <= target_price]

        if len(reached) > 0:
            entry_date = reached.iloc[0]['날짜']
            entry_price = target_price  # 목표가에 진입했다고 가정

            # 진입 이후의 데이터
            after_entry = df[df['날짜'] >= entry_date]
            if len(after_entry) > 0:
                max_after = after_entry['고가'].max()
                min_after = after_entry['저가'].min()
                max_return = (max_after - entry_price) / entry_price * 100
                min_return = (min_after - entry_price) / entry_price * 100
                entry_days = (entry_date - pd.to_datetime(breakthrough_date)).days
            else:
                max_return = 0
                min_return = 0
                entry_days = None
        else:
            # 조정가에 도달하지 못함
            entry_price = None
            max_return = None
            min_return = None
            entry_days = None

        correction_strategies[f'-{correction_pct}%'] = {
            '진입가능': entry_price is not None,
            '진입가': entry_price,
            '진입시점': entry_days,
            '최고수익률': max_return,
            '최저수익률': min_return,
        }

    # 변동성 계산
    volatility = calculate_volatility(df, min(20, len(df)))

    return {
        '종목코드': stock_code,
        '종목명': stock_name,
        '돌파일': breakthrough_date,
        '돌파가': breakthrough_price,
        '고점가격': peak_price,
        '저점가격': lowest_price,
        '고점도달일': peak_days,
        '저점도달일': lowest_days,
        '변동성': volatility,
        '즉시진입_최고수익률': immediate_max_return,
        '즉시진입_최저수익률': immediate_min_return,
        **{f'조정{k}_진입가능': v['진입가능'] for k, v in correction_strategies.items()},
        **{f'조정{k}_진입시점': v['진입시점'] for k, v in correction_strategies.items()},
        **{f'조정{k}_최고수익률': v['최고수익률'] for k, v in correction_strategies.items()},
        **{f'조정{k}_최저수익률': v['최저수익률'] for k, v in correction_strategies.items()},
    }


def classify_stock_characteristics(analysis_result):
    """
    종목 특성 분류
    - 변동성: 낮음/중간/높음
    - 고점 도달 속도: 빠름/보통/느림
    - 조정 발생: 있음/없음
    """
    if not analysis_result:
        return None

    volatility = analysis_result.get('변동성', 0) or 0
    peak_days = analysis_result.get('고점도달일', 999)

    # 변동성 분류
    if volatility < 2:
        vol_class = '낮음'
    elif volatility < 4:
        vol_class = '중간'
    else:
        vol_class = '높음'

    # 고점 도달 속도 분류
    if peak_days < 5:
        speed_class = '빠름'
    elif peak_days < 15:
        speed_class = '보통'
    else:
        speed_class = '느림'

    # 조정 발생 여부
    has_correction = analysis_result.get('조정-10%_진입가능', False)

    return {
        '변동성분류': vol_class,
        '속도분류': speed_class,
        '조정발생': has_correction,
    }


def find_best_strategy(analysis_result):
    """최적 전략 찾기"""
    if not analysis_result:
        return None

    immediate_return = analysis_result.get('즉시진입_최고수익률', 0) or 0

    best_strategy = '즉시진입'
    best_return = immediate_return

    for correction_pct in [5, 10, 15, 20]:
        key = f'조정-{correction_pct}%'
        if analysis_result.get(f'{key}_진입가능', False):
            correction_return = analysis_result.get(f'{key}_최고수익률', 0) or 0
            if correction_return > best_return:
                best_return = correction_return
                best_strategy = key

    return {
        '최적전략': best_strategy,
        '최적수익률': best_return,
    }


def main():
    # 1. 돌파 데이터 로드
    breakthrough_data = get_breakthrough_data()
    if not breakthrough_data:
        print("❌ 돌파 데이터가 없습니다.")
        return

    print(f"\n🔍 {len(breakthrough_data)}개 종목 분석 시작...\n")

    all_results = []
    analyzed_count = 0

    for stock in breakthrough_data:
        stock_code = stock['종목코드']
        stock_name = stock['종목명']

        # 각 기간별 돌파 분석 (1년, 2년, 3년, 4년, 5년)
        for period in ['1년', '2년', '3년', '4년', '5년']:
            breakthrough_date = stock.get(f'돌파일_{period}')
            breakthrough_price = stock.get(f'돌파가_{period}')

            if not breakthrough_date or not breakthrough_price:
                continue

            # 돌파 후 가격 데이터 조회 (최대 180일)
            start_date = breakthrough_date
            end_date = (pd.to_datetime(breakthrough_date) + timedelta(days=180)).strftime('%Y-%m-%d')

            prices = get_price_data(stock_code, start_date)
            if len(prices) < 5:
                continue

            # 전략 분석
            result = analyze_entry_strategy(
                stock_code,
                stock_name,
                breakthrough_date,
                breakthrough_price,
                prices
            )

            if result:
                result['돌파기간'] = period

                # 종목 특성 분류
                characteristics = classify_stock_characteristics(result)
                if characteristics:
                    result.update(characteristics)

                # 최적 전략 찾기
                best = find_best_strategy(result)
                if best:
                    result.update(best)

                all_results.append(result)
                analyzed_count += 1

                if analyzed_count % 10 == 0:
                    print(f"진행: {analyzed_count}개 돌파 케이스 분석 완료...")

    print(f"\n✓ 총 {analyzed_count}개 돌파 케이스 분석 완료\n")

    if not all_results:
        print("❌ 분석 결과가 없습니다.")
        return

    # 결과를 DataFrame으로 변환
    df = pd.DataFrame(all_results)

    # 2. 종합 분석
    print("=" * 80)
    print("📊 종합 분석 결과")
    print("=" * 80)

    # 2-1. 기간별 분석
    print("\n[1] 돌파 기간별 평균 수익률")
    print("-" * 80)
    period_analysis = df.groupby('돌파기간').agg({
        '즉시진입_최고수익률': 'mean',
        '즉시진입_최저수익률': 'mean',
        '조정-10%_최고수익률': 'mean',
        '고점도달일': 'mean',
    }).round(2)
    print(period_analysis)

    # 2-2. 변동성별 분석
    print("\n[2] 변동성별 최적 전략")
    print("-" * 80)
    volatility_strategy = df.groupby(['변동성분류', '최적전략']).size().unstack(fill_value=0)
    print(volatility_strategy)
    print("\n변동성별 평균 수익률:")
    vol_return = df.groupby('변동성분류')['최적수익률'].mean().round(2)
    print(vol_return)

    # 2-3. 속도별 분석
    print("\n[3] 고점 도달 속도별 최적 전략")
    print("-" * 80)
    speed_strategy = df.groupby(['속도분류', '최적전략']).size().unstack(fill_value=0)
    print(speed_strategy)
    print("\n속도별 평균 수익률:")
    speed_return = df.groupby('속도분류')['최적수익률'].mean().round(2)
    print(speed_return)

    # 2-4. 전략별 승률
    print("\n[4] 전략별 성과 비교")
    print("-" * 80)

    # 즉시 진입 전략
    immediate_positive = (df['즉시진입_최고수익률'] > 0).sum()
    immediate_total = df['즉시진입_최고수익률'].notna().sum()
    immediate_winrate = (immediate_positive / immediate_total * 100) if immediate_total > 0 else 0
    immediate_avg = df['즉시진입_최고수익률'].mean()

    print(f"즉시 진입: 승률 {immediate_winrate:.1f}% | 평균 수익률 {immediate_avg:.2f}%")

    # 조정 후 진입 전략들
    for correction_pct in [5, 10, 15, 20]:
        key = f'조정-{correction_pct}%'
        available = df[f'{key}_진입가능'].sum()
        positive = df[df[f'{key}_진입가능'] == True][f'{key}_최고수익률'].gt(0).sum()
        winrate = (positive / available * 100) if available > 0 else 0
        avg_return = df[df[f'{key}_진입가능'] == True][f'{key}_최고수익률'].mean()

        print(f"{key} 조정: 기회 {available}회 | 승률 {winrate:.1f}% | 평균 수익률 {avg_return:.2f}%")

    # 3. 결론 및 권장사항
    print("\n" + "=" * 80)
    print("💡 결론 및 투자 권장사항")
    print("=" * 80)

    # 변동성별 권장사항
    print("\n[변동성별 권장 전략]")
    for vol_class in ['낮음', '중간', '높음']:
        vol_data = df[df['변동성분류'] == vol_class]
        if len(vol_data) == 0:
            continue
        most_common_strategy = vol_data['최적전략'].mode()
        if len(most_common_strategy) > 0:
            strategy = most_common_strategy.iloc[0]
            avg_return = vol_data[vol_data['최적전략'] == strategy]['최적수익률'].mean()
            print(f"  {vol_class} 변동성 → {strategy} (평균 수익률: {avg_return:.2f}%)")

    # 속도별 권장사항
    print("\n[고점 도달 속도별 권장 전략]")
    for speed_class in ['빠름', '보통', '느림']:
        speed_data = df[df['속도분류'] == speed_class]
        if len(speed_data) == 0:
            continue
        most_common_strategy = speed_data['최적전략'].mode()
        if len(most_common_strategy) > 0:
            strategy = most_common_strategy.iloc[0]
            avg_return = speed_data[speed_data['최적전략'] == strategy]['최적수익률'].mean()
            print(f"  {speed_class} → {strategy} (평균 수익률: {avg_return:.2f}%)")

    # 4. 결과를 CSV로 저장
    output_dir = Path(__file__).parent.parent / 'analysis_results'
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / f'breakthrough_strategy_analysis_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✓ 상세 분석 결과가 저장되었습니다: {output_file}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
