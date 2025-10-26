"""
한국 주식 투자점수 계산 스크립트
- B포인트 기반 패턴 분석
- 투자점수 계산 (0-100점)
- pattern_predictions 테이블 업데이트
- 매일 기존 데이터 삭제 후 재계산
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from supabase import create_client, Client

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

print("=" * 60)
print("한국 주식 투자점수 계산 시작")
print(f"실행 시간(KST): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

def clear_old_predictions():
    """기존 예측 데이터 전체 삭제"""
    try:
        # 모든 데이터 삭제 (id가 0이 아닌 모든 행)
        response = supabase.table('pattern_predictions').delete().neq('id', 0).execute()
        print("기존 예측 데이터 삭제 완료")
        return True
    except Exception as e:
        print(f"ERROR clearing predictions: {e}")
        return False

def get_stock_list():
    """활성 종목 리스트 조회"""
    try:
        response = supabase.table('stocks').select('종목코드, 종목명, pattern').execute()
        stocks = response.data or []
        print(f"Found {len(stocks)} stocks")
        return stocks
    except Exception as e:
        print(f"ERROR getting stocks: {e}")
        return []

def get_current_price(stock_code):
    """최신 종가 조회"""
    try:
        response = supabase.table('prices').select('종가, 거래량, 날짜').eq('종목코드', stock_code).order('날짜', desc=True).limit(1).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except:
        return None

def get_latest_bt_point(stock_code):
    """최신 B포인트 조회"""
    try:
        response = supabase.table('bt_points').select('순번, b날짜, b가격').eq('종목코드', stock_code).order('순번', desc=True).limit(1).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except:
        return None

def get_recent_prices(stock_code, days=60):
    """최근 N일간 가격 데이터"""
    try:
        date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        response = supabase.table('prices').select('날짜, 종가, 거래량').eq('종목코드', stock_code).gte('날짜', date_from).order('날짜', desc=False).execute()
        return response.data or []
    except:
        return []

def calculate_elapsed_days(b_date):
    """B날짜로부터 경과일수 계산"""
    if not b_date:
        return None
    try:
        if isinstance(b_date, str):
            b_datetime = datetime.fromisoformat(b_date.replace('Z', '+00:00').split('T')[0])
        else:
            b_datetime = b_date
        elapsed = (datetime.now() - b_datetime).days
        return elapsed
    except:
        return None

def calculate_current_return(current_price, b_price):
    """현재 수익률 계산"""
    if not current_price or not b_price or b_price <= 0:
        return None
    return round(((current_price - b_price) / b_price * 100), 2)

def calculate_investment_score(current_price, b_price, pattern, prices):
    """투자점수 계산 (0-100점)"""
    if not current_price or not b_price or b_price <= 0:
        return None

    score = 0
    details = {}

    # 1. B가격 대비 현재가 위치 (30점)
    price_ratio = current_price / b_price
    if price_ratio >= 1.05:
        position_score = 30
        status = '돌파'
        breakthrough_prob = 90.0
    elif price_ratio >= 0.95:
        position_score = 25
        status = '돌파직전'
        breakthrough_prob = 70.0
    elif price_ratio >= 0.90:
        position_score = 15
        status = '박스권'
        breakthrough_prob = 40.0
    elif price_ratio >= 0.80:
        position_score = 5
        status = '조정'
        breakthrough_prob = 20.0
    else:
        position_score = 0
        status = '급락'
        breakthrough_prob = 5.0

    score += position_score
    details['현재상태'] = status
    details['돌파가능성'] = breakthrough_prob

    # 2. 패턴 점수 (25점)
    pattern_scores = {'돌파': 25, '돌파눌림': 20, '박스권': 12, '기타': 6, '이탈': 0}
    pattern_score = pattern_scores.get(pattern, 6)
    score += pattern_score
    details['메인패턴'] = pattern or '기타'
    details['차트점수'] = pattern_score

    # 3. 추세 점수 (20점)
    trend_score = 0
    trend_ratio = 0
    chart_trend = '중립'

    if len(prices) >= 20:
        recent_20 = [p['종가'] for p in prices[-20:] if p.get('종가')]
        if len(recent_20) >= 20:
            ma_first_10 = sum(recent_20[:10]) / 10
            ma_last_10 = sum(recent_20[-10:]) / 10
            trend_ratio = (ma_last_10 - ma_first_10) / ma_first_10 * 100 if ma_first_10 > 0 else 0

            if trend_ratio >= 10:
                trend_score = 20
                chart_trend = '강한상승'
            elif trend_ratio >= 5:
                trend_score = 15
                chart_trend = '상승'
            elif trend_ratio >= 0:
                trend_score = 10
                chart_trend = '약한상승'
            elif trend_ratio >= -5:
                trend_score = 5
                chart_trend = '약한하락'
            else:
                trend_score = 0
                chart_trend = '하락'

    score += trend_score
    details['추세'] = round(trend_ratio, 2)
    details['차트추세'] = chart_trend
    details['모멘텀'] = round(trend_ratio, 2)

    # 4. 변동성 점수 (15점)
    volatility_score = 0
    volatility = 0

    if len(prices) >= 20:
        recent_20_prices = [p['종가'] for p in prices[-20:] if p.get('종가')]
        if len(recent_20_prices) >= 20:
            avg_price = sum(recent_20_prices) / len(recent_20_prices)
            variance = sum((p - avg_price) ** 2 for p in recent_20_prices) / len(recent_20_prices)
            std_dev = variance ** 0.5
            volatility = (std_dev / avg_price * 100) if avg_price > 0 else 0

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
    details['변동성'] = round(volatility, 2)

    # 5. 거래량 점수 (10점)
    volume_score = 0
    if len(prices) >= 20:
        recent_volumes = [p['거래량'] for p in prices[-20:] if p.get('거래량')]
        if len(recent_volumes) >= 20 and len(recent_volumes) > 5:
            avg_volume = sum(recent_volumes[:-5]) / (len(recent_volumes) - 5)
            recent_5_avg = sum(recent_volumes[-5:]) / 5
            volume_ratio = (recent_5_avg / avg_volume) if avg_volume > 0 else 1

            if volume_ratio >= 1.5:
                volume_score = 10
            elif volume_ratio >= 1.2:
                volume_score = 7
            elif volume_ratio >= 0.8:
                volume_score = 5
            else:
                volume_score = 2

    score += volume_score

    # 추가 지표 계산
    details['B포인트품질'] = round((pattern_score / 25 * 50) + (volatility_score / 15 * 50), 1)
    details['구조강도'] = round((position_score / 30 * 50) + (trend_score / 20 * 50), 1)
    details['신뢰도'] = round(score, 1)

    # 매수 추천
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

def calculate_buy_prices(b_price):
    """5단계 매수가 계산"""
    if not b_price or b_price <= 0:
        return {}
    return {
        '매수1': round(b_price * 0.98, 0),
        '매수2': round(b_price * 0.96, 0),
        '매수3': round(b_price * 0.94, 0),
        '매수4': round(b_price * 0.92, 0),
        '매수5': round(b_price * 0.90, 0),
        '평균_매수가': round(b_price * 0.94, 0),
        '목표가': round(b_price * 1.20, 0),
        '목표_수익률': 20.0
    }

def calculate_expected_returns(current_price, b_price, prices):
    """예상 수익률 계산 (현재가 기준)"""
    if not prices or len(prices) < 30 or not current_price or current_price <= 0:
        return {'평균_예상수익률': 0, '최대_예상수익률': 0, '최소_예상수익률': 0, '평균_최고수익률': 0, '유사패턴_개수': 0, '평균_예상기간': 30}

    recent_highs = [p['종가'] for p in prices[-30:] if p.get('종가')]
    if not recent_highs or not b_price or b_price <= 0:
        return {'평균_예상수익률': 0, '최대_예상수익률': 0, '최소_예상수익률': 0, '평균_최고수익률': 0, '유사패턴_개수': 0, '평균_예상기간': 30}

    max_price = max(recent_highs)
    avg_price = sum(recent_highs) / len(recent_highs)
    min_price = min(recent_highs)

    # 현재가 기준으로 예상 수익률 계산 (과거 최고가 기준)
    return {
        '평균_예상수익률': round((avg_price - current_price) / current_price * 100, 2),
        '최대_예상수익률': round((max_price - current_price) / current_price * 100, 2),
        '최소_예상수익률': round((min_price - current_price) / current_price * 100, 2),
        '평균_최고수익률': round((max_price - current_price) / current_price * 100, 2),
        '유사패턴_개수': len(recent_highs),
        '평균_예상기간': 30
    }

def save_prediction(stock_code, stock_name, current_price_data, bt_point, score_details, buy_prices, expected_returns):
    """예측 데이터 저장"""
    try:
        current_price = current_price_data['종가'] if current_price_data else None
        b_price = bt_point['b가격'] if bt_point else None
        b_date = bt_point['b날짜'] if bt_point else None

        prediction_data = {
            '종목코드': stock_code,
            '종목명': stock_name,
            '분석일시': datetime.now().isoformat(),
            '현재가': current_price,
            '현재_b순번': bt_point['순번'] if bt_point else None,
            '현재_b날짜': b_date,
            '현재_b가격': b_price,
            '현재_경과일수': calculate_elapsed_days(b_date),
            '현재_수익률': calculate_current_return(current_price, b_price),
            '투자점수': score_details['투자점수'],
            '신뢰도': score_details.get('신뢰도', 0),
            '매수추천': score_details['매수추천'],
            '메인패턴': score_details['메인패턴'],
            '현재상태': score_details['현재상태'],
            '변동성': score_details.get('변동성', 0),
            '추세': score_details.get('추세', 0),
            '차트점수': score_details.get('차트점수', 0),
            '차트추세': score_details.get('차트추세', '중립'),
            '모멘텀': score_details.get('모멘텀', 0),
            '구조강도': score_details.get('구조강도', 0),
            'B포인트품질': score_details.get('B포인트품질', 0),
            '돌파가능성': score_details.get('돌파가능성', 0),
        }

        prediction_data.update(buy_prices)
        prediction_data.update(expected_returns)

        supabase.table('pattern_predictions').insert(prediction_data).execute()
        return True
    except Exception as e:
        print(f"  ERROR saving {stock_code}: {e}")
        return False

def main():
    try:
        # 1. 기존 데이터 삭제
        print("\n기존 데이터 삭제 중...")
        clear_old_predictions()

        # 2. 종목 조회
        stocks = get_stock_list()
        if not stocks:
            print("분석할 종목이 없습니다")
            return

        print(f"\n{len(stocks)}개 종목 분석 시작\n")

        success_count = 0
        score_dist = {'적극 매수': 0, '매수': 0, '관망': 0, '보류': 0, '비추천': 0}

        for stock in stocks:
            stock_code = stock['종목코드']
            stock_name = stock['종목명']
            pattern = stock.get('pattern', '기타')

            current_price_data = get_current_price(stock_code)
            if not current_price_data:
                continue

            bt_point = get_latest_bt_point(stock_code)
            if not bt_point or not bt_point.get('b가격'):
                continue

            prices = get_recent_prices(stock_code, days=60)
            if len(prices) < 20:
                continue

            score_details = calculate_investment_score(current_price_data['종가'], bt_point['b가격'], pattern, prices)
            if not score_details:
                continue

            buy_prices = calculate_buy_prices(bt_point['b가격'])
            expected_returns = calculate_expected_returns(current_price_data['종가'], bt_point['b가격'], prices)

            if save_prediction(stock_code, stock_name, current_price_data, bt_point, score_details, buy_prices, expected_returns):
                success_count += 1
                score_dist[score_details['매수추천']] += 1
                print(f"  OK {stock_name} ({stock_code}): {score_details['투자점수']}점 - {score_details['매수추천']}")

        print("\n" + "=" * 60)
        print("투자점수 분석 결과")
        print("=" * 60)
        for rec, cnt in score_dist.items():
            if cnt > 0:
                pct = (cnt / success_count * 100) if success_count > 0 else 0
                print(f"{rec}: {cnt}개 ({pct:.1f}%)")

        print(f"\n완료: {success_count}개 종목")
        print(f"완료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
