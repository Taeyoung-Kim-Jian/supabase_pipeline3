"""
신고가 돌파 전략 학습 모델
- 과거 돌파 데이터를 학습하여 최적 진입 전략 예측
- 종목 특성별 투자 전략 자동 분류
- 학습 결과를 DB에 저장하여 실시간 추천에 활용
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from supabase import create_client, Client
import pandas as pd
import numpy as np
import json
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
    ]
    for env_path in possible_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass

# Supabase 클라이언트 초기화
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("\nERROR: Environment variables not set")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("=" * 80)
print("신고가 돌파 전략 학습 모델")
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


def get_price_data(stock_code, start_date, days=180):
    """특정 종목의 가격 데이터 조회"""
    try:
        end_date = (pd.to_datetime(start_date) + timedelta(days=days)).strftime('%Y-%m-%d')
        response = supabase.table('prices').select('*').eq('종목코드', stock_code).gte('날짜', start_date).lte('날짜', end_date).order('날짜', desc=False).execute()
        return response.data or []
    except:
        return []


def calculate_features(stock_code, breakthrough_date, breakthrough_price, prices_after):
    """
    종목 특성 계산
    - 변동성, 고점/저점 도달 시점, 조정 패턴 등
    """
    if len(prices_after) < 5:
        return None

    df = pd.DataFrame(prices_after)
    df['날짜'] = pd.to_datetime(df['날짜'])
    df = df.sort_values('날짜')

    # 기본 통계
    peak_price = df['고가'].max()
    lowest_price = df['저가'].min()

    peak_date = df[df['고가'] == peak_price]['날짜'].iloc[0]
    lowest_date = df[df['저가'] == lowest_price]['날짜'].iloc[0]

    peak_days = (peak_date - pd.to_datetime(breakthrough_date)).days
    lowest_days = (lowest_date - pd.to_datetime(breakthrough_date)).days

    # 변동성 (20일 기준)
    if len(df) >= 20:
        returns = df.tail(20)['종가'].pct_change().dropna()
        volatility = returns.std() * 100 if len(returns) > 0 else 0
    else:
        returns = df['종가'].pct_change().dropna()
        volatility = returns.std() * 100 if len(returns) > 0 else 0

    # 거래량 변화 (돌파 전후 비교)
    avg_volume_after = df.head(10)['거래량'].mean() if len(df) >= 10 else df['거래량'].mean()

    # 조정 발생 여부 및 크기
    corrections = []
    for pct in [5, 10, 15, 20]:
        target = peak_price * (1 - pct / 100)
        if df['저가'].min() <= target:
            corrections.append(pct)

    max_correction = max(corrections) if corrections else 0

    # 수익률 계산
    max_return = (peak_price - breakthrough_price) / breakthrough_price * 100
    min_return = (lowest_price - breakthrough_price) / breakthrough_price * 100

    return {
        '종목코드': stock_code,
        '돌파일': breakthrough_date,
        '돌파가': breakthrough_price,
        '변동성': round(volatility, 2),
        '고점도달일': peak_days,
        '저점도달일': lowest_days,
        '최대조정률': max_correction,
        '평균거래량': int(avg_volume_after),
        '최고수익률': round(max_return, 2),
        '최저수익률': round(min_return, 2),
    }


def calculate_best_strategy(features, prices_after, breakthrough_price):
    """
    최적 전략 계산
    - 즉시 진입 vs 조정 후 진입 비교
    """
    df = pd.DataFrame(prices_after)
    df['날짜'] = pd.to_datetime(df['날짜'])
    df = df.sort_values('날짜')

    if len(df) == 0:
        return None

    peak_price = df['고가'].max()

    # 즉시 진입
    entry_immediate = df.iloc[0]['시가'] if len(df) > 0 else breakthrough_price
    immediate_return = (peak_price - entry_immediate) / entry_immediate * 100

    strategies = {
        '즉시진입': {
            '수익률': round(immediate_return, 2),
            '진입일': 0,
        }
    }

    # 조정 후 진입
    for correction_pct in [5, 10, 15, 20]:
        target = peak_price * (1 - correction_pct / 100)
        reached = df[df['저가'] <= target]

        if len(reached) > 0:
            entry_date = reached.iloc[0]['날짜']
            entry_days = (entry_date - df.iloc[0]['날짜']).days

            after_entry = df[df['날짜'] >= entry_date]
            if len(after_entry) > 0:
                max_after = after_entry['고가'].max()
                entry_return = (max_after - target) / target * 100

                strategies[f'조정{correction_pct}%'] = {
                    '수익률': round(entry_return, 2),
                    '진입일': entry_days,
                }

    # 최적 전략 선택
    best = max(strategies.items(), key=lambda x: x[1]['수익률'])

    return {
        '최적전략': best[0],
        '최적수익률': best[1]['수익률'],
        '진입시점': best[1]['진입일'],
        '전체전략': strategies,
    }


def train_model():
    """학습 데이터 생성 및 패턴 분석"""

    # 1. 돌파 데이터 로드
    breakthrough_data = get_breakthrough_data()
    if not breakthrough_data:
        print("❌ 돌파 데이터가 없습니다.")
        return None

    print(f"\n🔍 {len(breakthrough_data)}개 종목 분석 시작...\n")

    training_data = []
    processed = 0

    for stock in breakthrough_data:
        stock_code = stock['종목코드']
        stock_name = stock['종목명']

        # 각 기간별 돌파 분석
        for period in ['1년', '2년', '3년', '4년', '5년']:
            breakthrough_date = stock.get(f'돌파일_{period}')
            breakthrough_price = stock.get(f'돌파가_{period}')

            if not breakthrough_date or not breakthrough_price:
                continue

            # 가격 데이터 조회
            prices = get_price_data(stock_code, breakthrough_date, 180)
            if len(prices) < 5:
                continue

            # 특성 계산
            features = calculate_features(stock_code, breakthrough_date, breakthrough_price, prices)
            if not features:
                continue

            # 최적 전략 계산
            best_strategy = calculate_best_strategy(features, prices, breakthrough_price)
            if not best_strategy:
                continue

            # 데이터 병합
            record = {
                **features,
                '종목명': stock_name,
                '돌파기간': period,
                **best_strategy,
            }

            training_data.append(record)
            processed += 1

            if processed % 10 == 0:
                print(f"진행: {processed}개 케이스 처리 완료...")

    print(f"\n✓ 총 {processed}개 학습 데이터 생성 완료\n")

    if not training_data:
        print("❌ 학습 데이터가 없습니다.")
        return None

    return pd.DataFrame(training_data)


def create_strategy_rules(df):
    """
    규칙 기반 전략 생성
    - 변동성, 고점 도달 속도 등에 따른 최적 전략 분류
    """
    print("\n📊 전략 규칙 생성 중...")

    rules = {}

    # 변동성별 분류
    df['변동성구간'] = pd.cut(df['변동성'], bins=[0, 2, 4, 100], labels=['낮음', '중간', '높음'])

    # 고점 도달 속도별 분류
    df['속도구간'] = pd.cut(df['고점도달일'], bins=[0, 5, 15, 999], labels=['빠름', '보통', '느림'])

    # 돌파 기간별 분류
    period_map = {'1년': 1, '2년': 2, '3년': 3, '4년': 4, '5년': 5}
    df['기간점수'] = df['돌파기간'].map(period_map)

    # 규칙 생성
    for vol in ['낮음', '중간', '높음']:
        for speed in ['빠름', '보통', '느림']:
            subset = df[(df['변동성구간'] == vol) & (df['속도구간'] == speed)]

            if len(subset) >= 3:  # 최소 3개 이상의 샘플
                # 가장 많이 선택된 전략
                most_common = subset['최적전략'].mode()
                if len(most_common) > 0:
                    strategy = most_common.iloc[0]
                    avg_return = subset[subset['최적전략'] == strategy]['최적수익률'].mean()
                    win_rate = (subset[subset['최적전략'] == strategy]['최적수익률'] > 0).mean() * 100

                    rules[f'{vol}_{speed}'] = {
                        '추천전략': strategy,
                        '평균수익률': round(avg_return, 2),
                        '승률': round(win_rate, 1),
                        '샘플수': len(subset),
                    }

    print(f"✓ {len(rules)}개 규칙 생성 완료")
    return rules


def save_rules_to_db(rules):
    """규칙을 DB에 저장"""
    print("\n💾 규칙을 DB에 저장 중...")

    try:
        # 기존 규칙 삭제
        supabase.table('breakthrough_strategy_rules').delete().neq('id', 0).execute()

        # 새 규칙 저장
        for rule_name, rule_data in rules.items():
            parts = rule_name.split('_')

            record = {
                '변동성구간': parts[0],
                '속도구간': parts[1],
                '추천전략': rule_data['추천전략'],
                '평균수익률': rule_data['평균수익률'],
                '승률': rule_data['승률'],
                '샘플수': rule_data['샘플수'],
                '생성일시': datetime.now().isoformat(),
            }

            supabase.table('breakthrough_strategy_rules').insert(record).execute()

        print(f"✓ {len(rules)}개 규칙 저장 완료")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        return False


def print_analysis_summary(df, rules):
    """분석 결과 요약 출력"""
    print("\n" + "=" * 80)
    print("📊 학습 결과 요약")
    print("=" * 80)

    # 기간별 분석
    print("\n[1] 돌파 기간별 평균 수익률")
    print("-" * 80)
    period_summary = df.groupby('돌파기간').agg({
        '최고수익률': 'mean',
        '최저수익률': 'mean',
        '최적수익률': 'mean',
    }).round(2)
    print(period_summary)

    # 전략별 성과
    print("\n[2] 전략별 평균 수익률")
    print("-" * 80)
    strategy_summary = df.groupby('최적전략').agg({
        '최적수익률': ['mean', 'count'],
    }).round(2)
    print(strategy_summary)

    # 규칙 출력
    print("\n[3] 생성된 투자 전략 규칙")
    print("-" * 80)
    for rule_name, rule_data in sorted(rules.items()):
        parts = rule_name.split('_')
        print(f"\n변동성: {parts[0]} | 속도: {parts[1]}")
        print(f"  → 추천전략: {rule_data['추천전략']}")
        print(f"  → 평균 수익률: {rule_data['평균수익률']}%")
        print(f"  → 승률: {rule_data['승률']}%")
        print(f"  → 샘플수: {rule_data['샘플수']}개")


def main():
    # 1. 학습 데이터 생성
    df = train_model()
    if df is None or len(df) == 0:
        print("❌ 학습 실패")
        return

    # 2. 전략 규칙 생성
    rules = create_strategy_rules(df)

    # 3. 규칙을 DB에 저장
    save_rules_to_db(rules)

    # 4. 결과 요약 출력
    print_analysis_summary(df, rules)

    # 5. 학습 데이터를 CSV로 저장
    output_dir = Path(__file__).parent.parent / 'analysis_results'
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f'breakthrough_training_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✓ 학습 데이터가 저장되었습니다: {output_file}")

    # 6. 규칙을 JSON으로 저장
    rules_file = output_dir / f'breakthrough_rules_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(rules_file, 'w', encoding='utf-8') as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    print(f"✓ 규칙이 저장되었습니다: {rules_file}")

    print("\n" + "=" * 80)
    print("✅ 학습 완료!")
    print("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
