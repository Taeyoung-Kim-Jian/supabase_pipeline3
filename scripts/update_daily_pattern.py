"""
매일 패턴 업데이트 스크립트
- B포인트 기준으로 오늘 패턴 계산
- prices 테이블의 pattern 컬럼 갱신
- stocks 테이블의 pattern 컬럼 동기화
"""

import os
import sys
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
    print("ERROR: SUPABASE_URL 또는 SUPABASE_KEY 환경 변수가 설정되지 않았습니다.")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print("=" * 60)
print("매일 패턴 업데이트 시작")
print("=" * 60)

# SQL 파일 읽기
sql_file = Path(__file__).parent.parent / 'sql' / 'update_daily_pattern.sql'

if not sql_file.exists():
    print(f"ERROR: SQL 파일을 찾을 수 없습니다: {sql_file}")
    sys.exit(1)

with open(sql_file, 'r', encoding='utf-8') as f:
    sql_content = f.read()

# SQL 실행 (Supabase REST API를 통한 RPC 호출)
# 주의: Supabase Python 클라이언트는 직접 SQL 실행을 지원하지 않으므로
# PostgreSQL 함수로 래핑하거나 다른 방법 사용 필요

# 대안: psycopg2 사용
try:
    import psycopg2

    # DATABASE_URL 환경 변수 필요
    DATABASE_URL = os.getenv("DATABASE_URL")

    if not DATABASE_URL:
        print("WARNING: DATABASE_URL이 없어 psycopg2로 실행할 수 없습니다.")
        print("INFO: Supabase 대시보드에서 sql/update_daily_pattern.sql을 수동 실행하세요.")
        sys.exit(0)

    # PostgreSQL 연결
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    # SQL 실행
    cursor.execute(sql_content)
    conn.commit()

    print("OK: 패턴 업데이트 완료")

    cursor.close()
    conn.close()

except ImportError:
    print("INFO: psycopg2가 설치되지 않았습니다.")
    print("INFO: Supabase 대시보드에서 sql/update_daily_pattern.sql을 수동 실행하세요.")
except Exception as e:
    print(f"ERROR: 패턴 업데이트 실패 - {e}")
    sys.exit(1)
