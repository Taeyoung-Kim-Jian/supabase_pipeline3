"""
신규 신고가 돌파 종목 투자 전략 추천
- 학습된 규칙을 기반으로 신규 돌파 종목에 최적 진입 전략 제시
- 실시간으로 적용 가능한 자동 추천 시스템
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from supabase import create_client, Client
import pandas as pd
import numpy as np
import json

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
print("신규 돌파 종목 투자 전략 추천 시스템")
print(f"실행 시간(KST): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)


def get_strategy_rules():
    """DB에서 학습된 전략 규칙 로드"""
    print("\n📚 전략 규칙 로딩 중...")
    try:
        response = supabase.table('breakthrough_strategy_rules').select('*').execute()
        if response.data:
            print(f"✓ {len(response.data)}개 규칙 로드 완료")
            return response.data
        return []
    except Exception as e:
        print(f"ERROR: 규칙 로드 실패 - {e}")
        print("⚠️  train_breakthrough_model.py를 먼저 실행하여 규칙을 생성하세요.")
        return []


def get_recent_breakthroughs(days=30):
    """최근 N일 이내 돌파 종목 조회"""
    print(f"\n🔍 최근 {days}일 이내 돌파 종목 조회 중...")
    try:
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        response = supabase.table('kr_breakthrough_history').select('*').execute()

        if not response.data:
            return []

        recent_stocks = []
        for stock in response.data:
            for period in ['1년', '2년', '3년', '4년', '5년']:
                breakthrough_date = stock.get(f'돌파일_{period}')
                if breakthrough_date and breakthrough_date >= cutoff_date:
                    recent_stocks.append({
                        '종목코드': stock['종목코드'],
                        '종목명': stock['종목명'],
                        '돌파일': breakthrough_date,
                        '돌파가': stock.get(f'돌파가_{period}'),
                        '돌파기간': period,
                        '현재가': stock.get('현재가'),
                    })

        print(f"✓ {len(recent_stocks)}개 최근 돌파 종목 발견")
        return recent_stocks

    except Exception as e:
        print(f"ERROR: {e}")
        return []


def get_price_data(stock_code, start_date, days=60):
    """특정 종목의 가격 데이터 조회 (최근 60일)"""
    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        response = supabase.table('prices').select('*').eq('종목코드', stock_code).gte('날짜', start_date).lte('날짜', end_date).order('날짜', desc=False).execute()
        return response.data or []
    except:
        return []


def calculate_stock_characteristics(stock_code, breakthrough_date, prices_before, prices_after):
    """
    종목 특성 계산
    - 변동성: 최근 20일 기준
    - 고점 도달 속도: 돌파 후 고점까지 걸린 시간
    """
    if len(prices_after) < 5:
        return None

    df = pd.DataFrame(prices_after)
    df['날짜'] = pd.to_datetime(df['날짜'])
    df = df.sort_values('날짜')

    # 변동성 계산 (20일 기준)
    if len(df) >= 20:
        returns = df.tail(20)['종가'].pct_change().dropna()
        volatility = returns.std() * 100 if len(returns) > 0 else 0
    else:
        returns = df['종가'].pct_change().dropna()
        volatility = returns.std() * 100 if len(returns) > 0 else 0

    # 고점 도달 속도
    peak_price = df['고가'].max()
    peak_date = df[df['고가'] == peak_price]['날짜'].iloc[0]
    peak_days = (peak_date - pd.to_datetime(breakthrough_date)).days

    # 변동성 구간 분류
    if volatility < 2:
        volatility_class = '낮음'
    elif volatility < 4:
        volatility_class = '중간'
    else:
        volatility_class = '높음'

    # 속도 구간 분류
    if peak_days < 5:
        speed_class = '빠름'
    elif peak_days < 15:
        speed_class = '보통'
    else:
        speed_class = '느림'

    return {
        '변동성': round(volatility, 2),
        '변동성구간': volatility_class,
        '고점도달일': peak_days,
        '속도구간': speed_class,
    }


def find_matching_rule(characteristics, rules):
    """종목 특성에 맞는 규칙 찾기"""
    volatility_class = characteristics['변동성구간']
    speed_class = characteristics['속도구간']

    # 정확히 일치하는 규칙 찾기
    for rule in rules:
        if rule['변동성구간'] == volatility_class and rule['속도구간'] == speed_class:
            return rule

    # 일치하는 규칙이 없으면 기본 전략 (즉시진입)
    return None


def generate_recommendation(stock_info, characteristics, rule):
    """투자 추천 생성"""
    recommendation = {
        '종목코드': stock_info['종목코드'],
        '종목명': stock_info['종목명'],
        '돌파일': stock_info['돌파일'],
        '돌파가': stock_info['돌파가'],
        '현재가': stock_info['현재가'],
        '돌파기간': stock_info['돌파기간'],
        '변동성': characteristics['변동성'],
        '변동성구간': characteristics['변동성구간'],
        '고점도달일': characteristics['고점도달일'],
        '속도구간': characteristics['속도구간'],
    }

    if rule:
        recommendation.update({
            '추천전략': rule['추천전략'],
            '예상수익률': rule['평균수익률'],
            '전략승률': rule['승률'],
            '규칙샘플수': rule['샘플수'],
            '신뢰도': '높음' if rule['샘플수'] >= 10 else '보통' if rule['샘플수'] >= 5 else '낮음',
        })
    else:
        recommendation.update({
            '추천전략': '즉시진입',
            '예상수익률': None,
            '전략승률': None,
            '규칙샘플수': 0,
            '신뢰도': '규칙없음',
        })

    # 구체적인 진입가 계산
    current_price = stock_info['현재가']
    strategy = recommendation['추천전략']

    if strategy == '즉시진입':
        recommendation['권장진입가'] = current_price
        recommendation['대기여부'] = '즉시 진입'
    elif '조정' in strategy:
        # 조정5%, 조정10% 등에서 숫자 추출
        correction_pct = int(''.join(filter(str.isdigit, strategy)))
        target_price = current_price * (1 - correction_pct / 100)
        recommendation['권장진입가'] = round(target_price, 0)
        recommendation['대기여부'] = f'{correction_pct}% 조정 대기'
    else:
        recommendation['권장진입가'] = current_price
        recommendation['대기여부'] = '전략 확인 필요'

    return recommendation


def save_recommendations_to_db(recommendations):
    """추천 결과를 DB에 저장"""
    print("\n💾 추천 결과를 DB에 저장 중...")

    try:
        # 테이블이 없으면 생성하지 않고 스�ip (수동 생성 필요)
        for rec in recommendations:
            # 기존 추천이 있으면 업데이트, 없으면 삽입
            existing = supabase.table('breakthrough_recommendations').select('id').eq('종목코드', rec['종목코드']).eq('돌파일', rec['돌파일']).execute()

            record = {
                '종목코드': rec['종목코드'],
                '종목명': rec['종목명'],
                '돌파일': rec['돌파일'],
                '돌파가': rec['돌파가'],
                '현재가': rec['현재가'],
                '돌파기간': rec['돌파기간'],
                '변동성': rec['변동성'],
                '변동성구간': rec['변동성구간'],
                '고점도달일': rec['고점도달일'],
                '속도구간': rec['속도구간'],
                '추천전략': rec['추천전략'],
                '권장진입가': rec['권장진입가'],
                '대기여부': rec['대기여부'],
                '예상수익률': rec['예상수익률'],
                '전략승률': rec['전략승률'],
                '신뢰도': rec['신뢰도'],
                '생성일시': datetime.now().isoformat(),
            }

            if existing.data:
                # 업데이트
                supabase.table('breakthrough_recommendations').update(record).eq('id', existing.data[0]['id']).execute()
            else:
                # 삽입
                supabase.table('breakthrough_recommendations').insert(record).execute()

        print(f"✓ {len(recommendations)}개 추천 저장 완료")
        return True

    except Exception as e:
        print(f"⚠️  DB 저장 실패 (테이블이 없을 수 있습니다): {e}")
        print("   - SQL에서 breakthrough_recommendations 테이블을 생성하세요")
        return False


def print_recommendations(recommendations):
    """추천 결과 출력"""
    print("\n" + "=" * 80)
    print("📊 투자 전략 추천 결과")
    print("=" * 80)

    if not recommendations:
        print("\n⚠️  추천할 종목이 없습니다.")
        return

    # 신뢰도별로 정렬 (높음 > 보통 > 낮음 > 규칙없음)
    confidence_order = {'높음': 1, '보통': 2, '낮음': 3, '규칙없음': 4}
    sorted_recs = sorted(recommendations, key=lambda x: confidence_order.get(x['신뢰도'], 5))

    for i, rec in enumerate(sorted_recs, 1):
        print(f"\n[{i}] {rec['종목명']} ({rec['종목코드']})")
        print("-" * 80)
        print(f"  돌파일: {rec['돌파일']} ({rec['돌파기간']} 신고가 돌파)")
        print(f"  돌파가: {rec['돌파가']:,}원 → 현재가: {rec['현재가']:,}원")
        print(f"  변동성: {rec['변동성']}% ({rec['변동성구간']}) | 고점도달: {rec['고점도달일']}일 ({rec['속도구간']})")
        print(f"\n  🎯 추천 전략: {rec['추천전략']}")
        print(f"  💰 권장 진입가: {rec['권장진입가']:,}원 ({rec['대기여부']})")

        if rec['예상수익률'] is not None:
            print(f"  📈 예상 수익률: {rec['예상수익률']:.2f}% (승률 {rec['전략승률']:.1f}%)")

        confidence_emoji = {'높음': '🟢', '보통': '🟡', '낮음': '🟠', '규칙없음': '⚪'}
        print(f"  {confidence_emoji.get(rec['신뢰도'], '⚪')} 신뢰도: {rec['신뢰도']}", end='')
        if rec['규칙샘플수'] > 0:
            print(f" (학습 샘플: {rec['규칙샘플수']}개)")
        else:
            print()


def main():
    # 1. 전략 규칙 로드
    rules = get_strategy_rules()
    if not rules:
        print("\n❌ 전략 규칙이 없습니다.")
        print("   먼저 train_breakthrough_model.py를 실행하여 학습하세요.")
        return

    # 2. 최근 돌파 종목 조회
    recent_stocks = get_recent_breakthroughs(days=30)
    if not recent_stocks:
        print("\n✓ 최근 30일 이내 신규 돌파 종목이 없습니다.")
        return

    # 3. 각 종목별 추천 생성
    print(f"\n🔍 {len(recent_stocks)}개 종목 분석 시작...\n")
    recommendations = []

    for stock in recent_stocks:
        stock_code = stock['종목코드']
        stock_name = stock['종목명']
        breakthrough_date = stock['돌파일']

        print(f"분석 중: {stock_name} ({breakthrough_date} 돌파)")

        # 가격 데이터 조회
        prices = get_price_data(stock_code, breakthrough_date, days=60)
        if len(prices) < 5:
            print(f"  → 데이터 부족, 스킵")
            continue

        # 종목 특성 계산
        characteristics = calculate_stock_characteristics(stock_code, breakthrough_date, [], prices)
        if not characteristics:
            print(f"  → 특성 계산 실패, 스킵")
            continue

        # 규칙 매칭
        rule = find_matching_rule(characteristics, rules)

        # 추천 생성
        recommendation = generate_recommendation(stock, characteristics, rule)
        recommendations.append(recommendation)

        print(f"  ✓ 추천: {recommendation['추천전략']} (신뢰도: {recommendation['신뢰도']})")

    if not recommendations:
        print("\n⚠️  추천을 생성할 수 없습니다.")
        return

    # 4. 추천 결과 출력
    print_recommendations(recommendations)

    # 5. DB에 저장 (선택사항)
    save_recommendations_to_db(recommendations)

    # 6. CSV로 저장
    output_dir = Path(__file__).parent.parent / 'analysis_results'
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f'breakthrough_recommendations_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    df = pd.DataFrame(recommendations)
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✓ 추천 결과가 저장되었습니다: {output_file}")

    print("\n" + "=" * 80)
    print("✅ 추천 완료!")
    print("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
