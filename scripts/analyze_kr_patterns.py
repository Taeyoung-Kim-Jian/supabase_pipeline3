"""
한국 주식 패턴 분석 스크립트
- B가격 기반 패턴 분류 (돌파, 돌파눌림, 박스권, 이탈, 기타)
- stocks 테이블의 패턴 필드 업데이트
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
print("🇰🇷 한국 주식 패턴 분석 시작")
print(f"⏰ 실행 시간(KST): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

def classify_pattern(current_price, b_price, recent_high, recent_low):
    """
    주식 패턴 분류 로직

    Args:
        current_price: 현재가
        b_price: B가격 (저항선)
        recent_high: 최근 최고가
        recent_low: 최근 최저가

    Returns:
        패턴명 (돌파, 돌파눌림, 박스권, 이탈, 기타)
    """
    if not all([current_price, b_price]):
        return "기타"

    # 돌파: 현재가가 B가격보다 높음 (5% 이상)
    if current_price > b_price * 1.05:
        return "돌파"

    # 돌파눌림: 현재가가 B가격 근처 (±5% 이내)
    if b_price * 0.95 <= current_price <= b_price * 1.05:
        return "돌파눌림"

    # 이탈: 현재가가 B가격보다 10% 이상 낮음
    if current_price < b_price * 0.90:
        return "이탈"

    # 박스권: B가격보다 약간 낮음 (5~10% 사이)
    if b_price * 0.90 <= current_price < b_price * 0.95:
        return "박스권"

    return "기타"

def get_recent_price_range(stock_code, days=30):
    """
    최근 N일간의 최고가, 최저가 조회
    """
    date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    response = supabase.table('prices') \
        .select('종가') \
        .eq('종목코드', stock_code) \
        .gte('날짜', date_from) \
        .order('날짜', desc=True) \
        .execute()

    if not response.data:
        return None, None

    prices = [row['종가'] for row in response.data if row['종가']]
    if not prices:
        return None, None

    return max(prices), min(prices)

def analyze_patterns():
    """
    모든 한국 주식의 패턴 분석 및 업데이트
    """
    try:
        # 활성 종목 조회
        response = supabase.table('stocks') \
            .select('종목코드, 종목명, 현재가, b가격') \
            .eq('is_active', True) \
            .execute()

        if not response.data:
            print("⚠️ 분석할 활성 종목이 없습니다.")
            return

        stocks = response.data
        print(f"📊 분석 대상: {len(stocks)}개 종목")

        updated_count = 0
        pattern_stats = {
            "돌파": 0,
            "돌파눌림": 0,
            "박스권": 0,
            "이탈": 0,
            "기타": 0
        }

        for stock in stocks:
            stock_code = stock['종목코드']
            stock_name = stock['종목명']
            current_price = stock['현재가']
            b_price = stock['b가격']

            # 최근 가격 범위 조회
            recent_high, recent_low = get_recent_price_range(stock_code, days=30)

            # 패턴 분류
            pattern = classify_pattern(current_price, b_price, recent_high, recent_low)

            # 패턴 업데이트
            update_response = supabase.table('stocks') \
                .update({'패턴': pattern}) \
                .eq('종목코드', stock_code) \
                .execute()

            if update_response.data:
                updated_count += 1
                pattern_stats[pattern] += 1
                print(f"  ✓ {stock_name} ({stock_code}): {pattern}")

        print("\n" + "=" * 60)
        print("📈 패턴 분석 결과")
        print("=" * 60)
        for pattern, count in pattern_stats.items():
            if count > 0:
                percentage = (count / updated_count * 100) if updated_count > 0 else 0
                icon = "🚀" if pattern == "돌파" else \
                       "📈" if pattern == "돌파눌림" else \
                       "📊" if pattern == "박스권" else \
                       "📉" if pattern == "이탈" else "⚪"
                print(f"{icon} {pattern}: {count}개 ({percentage:.1f}%)")

        print(f"\n✅ 총 {updated_count}개 종목 패턴 업데이트 완료")
        print(f"⏰ 완료 시간(KST): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

    except Exception as e:
        print(f"❌ 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    analyze_patterns()
