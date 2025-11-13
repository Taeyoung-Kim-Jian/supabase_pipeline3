"""
RLS 정책 수정 스크립트
- recommended_stocks 테이블의 RLS를 비활성화하여 insert 허용
"""

import os
import sys
from pathlib import Path

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
    for env_path in possible_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"✓ .env 파일 로드: {env_path}")
            break
except ImportError:
    print("⚠️  python-dotenv가 설치되지 않았습니다.")

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("\n❌ DATABASE_URL 환경변수가 설정되지 않았습니다.")
    print("\n.env 파일에 다음을 추가하세요:")
    print("DATABASE_URL=postgresql://postgres:[비밀번호]@db.sssmldmhcfuodutvvcqf.supabase.co:5432/postgres")
    sys.exit(1)

try:
    import psycopg2

    print("\n" + "=" * 80)
    print("recommended_stocks 테이블 RLS 정책 수정")
    print("=" * 80)

    # PostgreSQL 연결
    print("\n📡 데이터베이스 연결 중...")
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    # SQL 실행
    sql_commands = [
        "DROP POLICY IF EXISTS \"Allow public read access\" ON recommended_stocks;",
        "DROP POLICY IF EXISTS \"Allow service role full access\" ON recommended_stocks;",
        "DROP POLICY IF EXISTS \"Allow authenticated insert\" ON recommended_stocks;",
        "DROP POLICY IF EXISTS \"Allow authenticated update\" ON recommended_stocks;",
        "DROP POLICY IF EXISTS \"Allow authenticated delete\" ON recommended_stocks;",
        "ALTER TABLE recommended_stocks DISABLE ROW LEVEL SECURITY;",
    ]

    for sql in sql_commands:
        try:
            cursor.execute(sql)
            print(f"✓ {sql[:60]}...")
        except Exception as e:
            print(f"⚠️  {sql[:60]}... - {e}")

    conn.commit()

    # 확인
    cursor.execute("""
        SELECT tablename, rowsecurity
        FROM pg_tables
        WHERE schemaname = 'public'
        AND tablename = 'recommended_stocks';
    """)
    result = cursor.fetchone()

    if result:
        print(f"\n✓ 테이블: {result[0]}")
        print(f"✓ RLS 활성화: {result[1]}")

        if not result[1]:
            print("\n🎉 RLS가 성공적으로 비활성화되었습니다!")
            print("이제 recommend_stocks.py를 다시 실행하세요.")
        else:
            print("\n⚠️  RLS가 여전히 활성화되어 있습니다.")

    cursor.close()
    conn.close()

except ImportError:
    print("\n❌ psycopg2가 설치되지 않았습니다.")
    print("설치: pip install psycopg2-binary")
    sys.exit(1)
except Exception as e:
    print(f"\n❌ 오류 발생: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
