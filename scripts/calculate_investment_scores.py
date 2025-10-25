"""
한국 주식 투자점수 계산 스크립트
- B포인트 기반 패턴 분석
- 투자점수 계산 (0-100점)
- pattern_predictions 테이블 업데이트
"""

import os
import sys
from datetime import datetime, timedelta
from supabase import create_client, Client

# Supabase 클라이언트 초기화
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 환경 변수가 설정되지 않았습니다: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("=" * 60)
print("📊 한국 주식 투자점수 계산 시작")
print(f"⏰ 실행 시간(KST): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

def get_stock_data():
    """활성 종목 데이터 조회"""
    try:
        response = supabase.table('stocks') \
            .select('종목코드, 종목명, 현재가, b가격, 패턴') \
            .eq('is_active', True) \
            .execute()

        return response.data or []
    except Exception as e:
        print(f"❌ 종목 데이터 조회 오류: {str(e)}")
        return []

def get_bt_points(stock_code):
    """종목의 B포인트 데이터 조회"""
    try:
        response = supabase.table('bt_points') \
            .select('순번, b날짜, b가격') \
            .eq('종목코드', stock_code) \
            .order('순번', desc=True) \
            .limit(1) \
            .execute()

        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"  ⚠️ B포인트 조회 오류 ({stock_code}): {str(e)}")
        return None

def get_recent_prices(stock_code, days=60):
    """최근 N일간의 가격 데이터 조회"""
    try:
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        response = supabase.table('prices') \
            .select('날짜, 종가, 거래량') \
            .eq('종목코드', stock_code) \
            .gte('날짜', date_from) \
            .order('날짜', desc=False) \
            .execute()

        return response.data or []
    except Exception as e:
        print(f"  ⚠️ 가격 데이터 조회 오류 ({stock_code}): {str(e)}")
        return []

def calculate_investment_score(stock, bt_point, prices):
    """
    투자점수 계산 (0-100점)

    점수 구성:
    1. B가격 대비 현재가 위치 (30점)
    2. 패턴 점수 (25점)
    3. 추세 점수 (20점)
    4. 변동성 점수 (15점)
    5. 거래량 점수 (10점)
    """

    current_price = stock['현재가']
    b_price = stock['b가격'] or bt_point['b가격'] if bt_point else None
    pattern = stock['패턴']

    if not current_price or not b_price or b_price <= 0:
        return None

    score = 0
    details = {}

    # 1. B가격 대비 현재가 위치 (30점)
    price_ratio = current_price / b_price
    if price_ratio >= 1.05:  # 5% 이상 돌파
        position_score = 30
    elif price_ratio >= 0.95:  # ±5% 이내 (돌파 직전)
        position_score = 25
    elif price_ratio >= 0.90:  # 5-10% 하락 (박스권)
        position_score = 15
    elif price_ratio >= 0.80:  # 10-20% 하락
        position_score = 5
    else:  # 20% 이상 하락
        position_score = 0

    score += position_score
    details['위치점수'] = position_score
    details['현재상태'] = '돌파' if price_ratio >= 1.05 else '돌파직전' if price_ratio >= 0.95 else '박스권' if price_ratio >= 0.90 else '조정'

    # 2. 패턴 점수 (25점)
    pattern_scores = {
        '돌파': 25,
        '돌파눌림': 20,
        '박스권': 12,
        '기타': 6,
        '이탈': 0
    }
    pattern_score = pattern_scores.get(pattern, 6)
    score += pattern_score
    details['패턴점수'] = pattern_score
    details['메인패턴'] = pattern or '기타'

    # 3. 추세 점수 (20점)
    if len(prices) >= 20:
        recent_20 = [p['종가'] for p in prices[-20:] if p['종가']]
        if len(recent_20) >= 20:
            # 20일 이동평균 추세
            ma_first_10 = sum(recent_20[:10]) / 10
            ma_last_10 = sum(recent_20[-10:]) / 10
            trend_ratio = (ma_last_10 - ma_first_10) / ma_first_10 * 100

            if trend_ratio >= 10:  # 10% 이상 상승추세
                trend_score = 20
            elif trend_ratio >= 5:  # 5-10% 상승추세
                trend_score = 15
            elif trend_ratio >= 0:  # 0-5% 상승추세
                trend_score = 10
            elif trend_ratio >= -5:  # 0-5% 하락추세
                trend_score = 5
            else:  # 5% 이상 하락추세
                trend_score = 0

            score += trend_score
            details['추세점수'] = trend_score
            details['추세'] = trend_ratio
        else:
            details['추세점수'] = 0
            details['추세'] = 0
    else:
        details['추세점수'] = 0
        details['추세'] = 0

    # 4. 변동성 점수 (15점)
    if len(prices) >= 20:
        recent_20_prices = [p['종가'] for p in prices[-20:] if p['종가']]
        if len(recent_20_prices) >= 20:
            avg_price = sum(recent_20_prices) / len(recent_20_prices)
            variance = sum((p - avg_price) ** 2 for p in recent_20_prices) / len(recent_20_prices)
            std_dev = variance ** 0.5
            volatility = (std_dev / avg_price * 100) if avg_price > 0 else 0

            # 낮은 변동성이 좋음 (10-20%가 적정)
            if volatility <= 10:
                volatility_score = 15
            elif volatility <= 15:
                volatility_score = 12
            elif volatility <= 20:
                volatility_score = 8
            elif volatility <= 30:
                volatility_score = 4
            else:
                volatility_score = 0

            score += volatility_score
            details['변동성점수'] = volatility_score
            details['변동성'] = round(volatility, 2)
        else:
            details['변동성점수'] = 0
            details['변동성'] = 0
    else:
        details['변동성점수'] = 0
        details['변동성'] = 0

    # 5. 거래량 점수 (10점)
    if len(prices) >= 20:
        recent_volumes = [p['거래량'] for p in prices[-20:] if p['거래량']]
        if len(recent_volumes) >= 20:
            avg_volume = sum(recent_volumes[:-5]) / (len(recent_volumes) - 5)
            recent_5_avg = sum(recent_volumes[-5:]) / 5
            volume_ratio = (recent_5_avg / avg_volume) if avg_volume > 0 else 1

            # 최근 거래량 증가가 좋음
            if volume_ratio >= 1.5:  # 50% 이상 증가
                volume_score = 10
            elif volume_ratio >= 1.2:  # 20-50% 증가
                volume_score = 7
            elif volume_ratio >= 0.8:  # 정상 범위
                volume_score = 5
            else:  # 거래량 감소
                volume_score = 2

            score += volume_score
            details['거래량점수'] = volume_score
        else:
            details['거래량점수'] = 0
    else:
        details['거래량점수'] = 0

    # 매수 추천 결정
    if score >= 80:
        recommendation = '적극 매수'
    elif score >= 70:
        recommendation = '매수'
    elif score >= 60:
        recommendation = '관망'
    elif score >= 40:
        recommendation = '보류'
    else:
        recommendation = '비추천'

    details['투자점수'] = round(score, 1)
    details['매수추천'] = recommendation

    return details

def calculate_buy_prices(current_price, b_price):
    """5단계 매수가 계산"""
    if not current_price or not b_price:
        return None

    # B가격 기준으로 5단계 매수가 계산
    buy_prices = {
        '매수1': round(b_price * 0.98, 0),  # -2%
        '매수2': round(b_price * 0.96, 0),  # -4%
        '매수3': round(b_price * 0.94, 0),  # -6%
        '매수4': round(b_price * 0.92, 0),  # -8%
        '매수5': round(b_price * 0.90, 0),  # -10%
    }

    buy_prices['평균_매수가'] = round(sum(buy_prices.values()) / 5, 0)

    # 목표가: B가격 + 20%
    buy_prices['목표가'] = round(b_price * 1.20, 0)
    buy_prices['목표_수익률'] = 20.0

    return buy_prices

def save_prediction(stock, bt_point, score_details, buy_prices):
    """투자점수 및 예측 데이터 저장"""
    try:
        prediction_data = {
            '종목코드': stock['종목코드'],
            '종목명': stock['종목명'],
            '분석일시': datetime.now().isoformat(),
            '현재가': stock['현재가'],
            '현재_b순번': bt_point['순번'] if bt_point else None,
            '현재_b날짜': bt_point['b날짜'] if bt_point else None,
            '현재_b가격': bt_point['b가격'] if bt_point else stock['b가격'],
            '투자점수': score_details['투자점수'],
            '매수추천': score_details['매수추천'],
            '메인패턴': score_details['메인패턴'],
            '현재상태': score_details['현재상태'],
            '변동성': score_details.get('변동성', 0),
            '추세': score_details.get('추세', 0),
        }

        if buy_prices:
            prediction_data.update(buy_prices)

        # 기존 데이터 삭제 후 삽입 (종목별 최신 데이터만 유지할 수도 있음)
        response = supabase.table('pattern_predictions') \
            .insert(prediction_data) \
            .execute()

        return True
    except Exception as e:
        print(f"  ❌ 저장 오류 ({stock['종목코드']}): {str(e)}")
        return False

def main():
    """메인 실행 함수"""
    try:
        stocks = get_stock_data()

        if not stocks:
            print("⚠️ 분석할 종목이 없습니다.")
            return

        print(f"📊 분석 대상: {len(stocks)}개 종목\n")

        success_count = 0
        score_distribution = {
            '적극 매수': 0,
            '매수': 0,
            '관망': 0,
            '보류': 0,
            '비추천': 0
        }

        for stock in stocks:
            stock_code = stock['종목코드']
            stock_name = stock['종목명']

            # B포인트 조회
            bt_point = get_bt_points(stock_code)

            # 최근 가격 데이터 조회
            prices = get_recent_prices(stock_code, days=60)

            if not prices:
                print(f"  ⚠️ {stock_name} ({stock_code}): 가격 데이터 부족")
                continue

            # 투자점수 계산
            score_details = calculate_investment_score(stock, bt_point, prices)

            if not score_details:
                print(f"  ⚠️ {stock_name} ({stock_code}): 점수 계산 실패")
                continue

            # 매수가 계산
            b_price = stock['b가격'] or (bt_point['b가격'] if bt_point else None)
            buy_prices = calculate_buy_prices(stock['현재가'], b_price)

            # 데이터 저장
            if save_prediction(stock, bt_point, score_details, buy_prices):
                success_count += 1
                score_distribution[score_details['매수추천']] += 1

                icon = '🚀' if score_details['투자점수'] >= 80 else \
                       '📈' if score_details['투자점수'] >= 70 else \
                       '⭐' if score_details['투자점수'] >= 60 else \
                       '📊' if score_details['투자점수'] >= 40 else '⚪'

                print(f"  {icon} {stock_name} ({stock_code}): {score_details['투자점수']}점 - {score_details['매수추천']}")

        print("\n" + "=" * 60)
        print("📈 투자점수 분석 결과")
        print("=" * 60)
        for recommendation, count in score_distribution.items():
            if count > 0:
                percentage = (count / success_count * 100) if success_count > 0 else 0
                icon = "🚀" if recommendation == "적극 매수" else \
                       "📈" if recommendation == "매수" else \
                       "⭐" if recommendation == "관망" else \
                       "📊" if recommendation == "보류" else "⚪"
                print(f"{icon} {recommendation}: {count}개 ({percentage:.1f}%)")

        print(f"\n✅ 총 {success_count}개 종목 투자점수 계산 완료")
        print(f"⏰ 완료 시간(KST): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

    except Exception as e:
        print(f"❌ 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
