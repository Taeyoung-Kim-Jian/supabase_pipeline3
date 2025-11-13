-- recommended_stocks 테이블의 RLS 정책 수정
-- 기존 정책 삭제 후 재생성

-- 1. 기존 정책 모두 삭제
DROP POLICY IF EXISTS "Allow public read access" ON recommended_stocks;
DROP POLICY IF EXISTS "Allow service role full access" ON recommended_stocks;
DROP POLICY IF EXISTS "Allow authenticated insert" ON recommended_stocks;
DROP POLICY IF EXISTS "Allow authenticated update" ON recommended_stocks;
DROP POLICY IF EXISTS "Allow authenticated delete" ON recommended_stocks;

-- 2. RLS 비활성화 (또는 모든 작업 허용)
-- 옵션 A: RLS 완전 비활성화 (가장 간단)
ALTER TABLE recommended_stocks DISABLE ROW LEVEL SECURITY;

-- 옵션 B: RLS 유지하면서 모든 작업 허용 (아래 주석 해제)
/*
ALTER TABLE recommended_stocks ENABLE ROW LEVEL SECURITY;

-- 읽기: 누구나 가능
CREATE POLICY "Allow all read"
ON recommended_stocks
FOR SELECT
USING (true);

-- 쓰기: 누구나 가능 (개발용)
CREATE POLICY "Allow all write"
ON recommended_stocks
FOR ALL
USING (true)
WITH CHECK (true);
*/

-- 확인
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
AND tablename = 'recommended_stocks';
