"""
한국 주식 패턴 분석 스크립트
- B가격 기반 패턴 분류 (돌파, 돌파눌림, 박스권, 이탈, 기타)
- stocks 테이블의 pattern 필드 업데이트
"""

import os
import sys
from datetime import datetime
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
print("Korean Stock Pattern Analysis")
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

def classify_pattern(current_price, b_prices_list):
    """
    Pattern classification based on ALL B-prices
    - 최고, 두번째, 중간, 최저 B가격을 기준으로 패턴 분류
    """
    if not current_price or not b_prices_list or len(b_prices_list) == 0:
        return '기타'

    # B가격 정렬
    sorted_b = sorted(b_prices_list)

    max_b = sorted_b[-1]  # 최고 B가격
    second_b = sorted_b[-2] if len(sorted_b) > 1 else sorted_b[0]  # 두번째 B가격
    mid_b = sorted_b[len(sorted_b) // 2]  # 중간 B가격
    min_b = sorted_b[0]  # 최저 B가격

    # 패턴 분류
    if current_price > max_b:
        return '돌파'
    elif current_price > second_b:
        return '돌파눌림'
    elif current_price > mid_b:
        return '박스권'
    elif current_price >= min_b:
        return '이탈'
    else:
        return '붕괴'

def get_current_price(stock_code):
    """Get latest price"""
    try:
        response = supabase.table('prices').select('종가').eq('종목코드', stock_code).order('날짜', desc=True).limit(1).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]['종가']
        return None
    except:
        return None

def get_all_bt_points(stock_code):
    """Get ALL B-prices for pattern classification"""
    try:
        response = supabase.table('bt_points').select('b가격').eq('종목코드', stock_code).order('순번', desc=False).execute()
        if response.data and len(response.data) > 0:
            return [point['b가격'] for point in response.data if point.get('b가격')]
        return []
    except:
        return []

def analyze_patterns():
    """Analyze all stocks and update patterns"""
    try:
        response = supabase.table('stocks').select('종목코드, 종목명').execute()
        if not response.data:
            print("No stocks found")
            return

        stocks = response.data
        print(f"Analyzing {len(stocks)} stocks\n")

        updated_count = 0
        pattern_stats = {"돌파": 0, "돌파눌림": 0, "박스권": 0, "이탈": 0, "붕괴": 0, "기타": 0}

        for stock in stocks:
            stock_code = stock['종목코드']
            stock_name = stock['종목명']

            current_price = get_current_price(stock_code)
            if not current_price:
                continue

            b_prices_list = get_all_bt_points(stock_code)
            if not b_prices_list or len(b_prices_list) == 0:
                continue

            pattern = classify_pattern(current_price, b_prices_list)

            try:
                supabase.table('stocks').update({'pattern': pattern}).eq('종목코드', stock_code).execute()
                updated_count += 1
                pattern_stats[pattern] += 1
                print(f"  OK {stock_name} ({stock_code}): {pattern}")
            except Exception as e:
                print(f"  ERROR {stock_name} ({stock_code}): {e}")

        print("\n" + "=" * 60)
        print("Pattern Analysis Results")
        print("=" * 60)
        for pattern, count in pattern_stats.items():
            if count > 0:
                pct = (count / updated_count * 100) if updated_count > 0 else 0
                print(f"{pattern}: {count} ({pct:.1f}%)")

        print(f"\nCompleted: {updated_count} stocks updated")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    analyze_patterns()
