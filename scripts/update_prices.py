# -*- coding: utf-8 -*-
"""
ECONews Daily Price Updater (네이버 금융 기반 v2)
------------------------------------------------------
📅 실행 주기: 매일 오후 4시 (KST, GitHub Actions 기준)
기능:
  ✅ Supabase의 stocks 목록 불러오기
  ✅ 네이버 금융에서 시세 스크래핑
  ✅ 실제 거래일과 오늘 날짜 비교 → 휴일 감지 후 업데이트 방지
  ✅ 거래량이 0인 경우 prices 미업데이트, stocks.마지막업데이트일만 갱신
  ✅ Supabase에 결과 upsert
  ✅ 이후 update_patterns.sql 호출로 패턴 자동 계산
------------------------------------------------------
"""

import os
import datetime
import pytz
import time
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

# ======================================
# 1️⃣ Supabase 연결
# ======================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("❌ SUPABASE 환경 변수가 설정되어 있지 않습니다.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ======================================
# 2️⃣ 현재 날짜 (한국시간)
# ======================================
KST = pytz.timezone("Asia/Seoul")
now = datetime.datetime.now(KST)
today = now.strftime("%Y-%m-%d")

print(f"🚀 ECONews Daily Price Updater Started at {now.strftime('%Y-%m-%d %H:%M:%S')} (KST)\n")

# ======================================
# 3️⃣ 네이버 금융 HTML 스크래핑 함수
# ======================================
def fetch_price_from_naver(code: str):
    """네이버 금융에서 가장 최근 거래일 시세 가져오기"""
    try:
        url = f"https://finance.naver.com/item/sise_day.naver?code={code}"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(res.text, "html.parser")

        rows = soup.select("table.type2 tr")
        valid_rows = [r for r in rows if len(r.select("td")) == 7 and r.select_one("td span")]

        if not valid_rows:
            return None

        cols = [c.text.strip().replace(",", "") for c in valid_rows[0].select("td")]
        if len(cols) < 7 or cols[0] == "":
            return None

        return {
            "date": cols[0].replace(".", "-"),
            "close": float(cols[1]),
            "open": float(cols[3]),
            "high": float(cols[4]),
            "low": float(cols[5]),
            "volume": float(cols[6]),
        }

    except Exception as e:
        print(f"❌ 스크래핑 오류 ({code}):", e)
        return None

# ======================================
# 4️⃣ Supabase stocks 목록 가져오기
# ======================================
stocks = supabase.table("stocks").select("종목코드, 종목명").execute().data
print(f"📦 {len(stocks)}개 종목 업데이트 시작\n")

updated_count = 0
skipped_count = 0
holiday_count = 0
error_count = 0

# ======================================
# 5️⃣ 메인 루프: 각 종목 업데이트
# ======================================
for i, stock in enumerate(stocks, 1):
    code = stock["종목코드"]
    name = stock["종목명"]

    data = fetch_price_from_naver(code)
    if not data:
        error_count += 1
        print(f"⚠️ {i}/{len(stocks)} {code} ({name}): 데이터를 가져오지 못함")
        continue

    trade_date = data["date"]

    # ✅ 휴일 감지
    if trade_date != today:
        supabase.table("stocks").update({"마지막업데이트일": today}).eq("종목코드", code).execute()
        holiday_count += 1
        print(f"🛑 {i}/{len(stocks)} {code} ({name}) 휴일 감지 ({trade_date}) → 업데이트 건너뜀")
        continue

    close, open_, high, low, volume = (
        data["close"],
        data["open"],
        data["high"],
        data["low"],
        data["volume"],
    )

    # ✅ 거래량이 0이면 prices 미업데이트
    if volume == 0:
        supabase.table("stocks").update({"마지막업데이트일": today}).eq("종목코드", code).execute()
        skipped_count += 1
        print(f"🔸 {i}/{len(stocks)} {code} ({name}) 거래량 0 → 날짜만 갱신")
        continue

    # ✅ prices 테이블 업데이트
    supabase.table("prices").upsert({
        "날짜": trade_date,
        "종목코드": code,
        "종목명": name,
        "종가": close,
        "시가": open_,
        "고가": high,
        "저가": low,
        "거래량": volume,
    }).execute()

    # ✅ stocks 테이블 업데이트
    supabase.table("stocks").update({"마지막업데이트일": today}).eq("종목코드", code).execute()

    updated_count += 1
    print(f"✅ {i}/{len(stocks)} {code} ({name}) 업데이트 완료 ({trade_date})")

    time.sleep(0.4)

# ======================================
# 6️⃣ 요약 로그
# ======================================
print("\n📊 업데이트 결과 요약 -----------------------------------")
print(f"✅ 가격 업데이트 완료: {updated_count}개")
print(f"⏸ 거래량 0 (휴일): {skipped_count}개")
print(f"🛑 휴일 감지 (이전 거래일): {holiday_count}개")
print(f"⚠️ 스크래핑 실패: {error_count}개")
print(f"🎯 Completed at {now.strftime('%Y-%m-%d %H:%M:%S')} (KST)")
