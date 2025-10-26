-- ================================
-- 매일 패턴 업데이트 스크립트
-- ================================
-- 목적: 오늘 날짜의 패턴을 B포인트 기준으로 계산 및 갱신
-- 실행: GitHub Actions 또는 수동 실행

-- 1️⃣ 오늘 패턴 초기화
UPDATE prices
SET pattern = NULL
WHERE 날짜 = CURRENT_DATE;

-- 2️⃣ 오늘 b포인트 기준 패턴 계산 및 갱신
DO $$
DECLARE
    rec RECORD;
    b_prices FLOAT[];
    b_dates DATE[];
    current_price FLOAT;
    sorted_b FLOAT[];
    max_b FLOAT;
    second_b FLOAT;
    mid_b FLOAT;
    min_b FLOAT;
    pat TEXT;
BEGIN
    -- 모든 종목 반복
    FOR rec IN SELECT DISTINCT 종목코드 FROM bt_points LOOP

        -- b포인트 날짜와 가격 배열 가져오기 (오늘 이전 b포인트만)
        SELECT ARRAY_AGG(b가격 ORDER BY b날짜),
               ARRAY_AGG(b날짜 ORDER BY b날짜)
        INTO b_prices, b_dates
        FROM bt_points
        WHERE 종목코드 = rec.종목코드
          AND b날짜 <= CURRENT_DATE;

        -- 오늘 종가 가져오기
        SELECT 종가 INTO current_price
        FROM prices
        WHERE 종목코드 = rec.종목코드
          AND 날짜 = CURRENT_DATE;

        -- 오늘 데이터 없으면 마지막 종가로 삽입
        IF current_price IS NULL THEN
            SELECT 종가 INTO current_price
            FROM prices
            WHERE 종목코드 = rec.종목코드
            ORDER BY 날짜 DESC
            LIMIT 1;

            INSERT INTO prices(종목코드, 날짜, 종가)
            VALUES (rec.종목코드, CURRENT_DATE, current_price)
            ON CONFLICT(종목코드, 날짜) DO NOTHING;
        END IF;

        -- b_prices 정렬
        sorted_b := ARRAY(SELECT unnest(b_prices) ORDER BY 1);

        -- 최고, 두번째, 중간, 최저 b가격 추출
        SELECT sorted_b[array_length(sorted_b,1)],
               CASE WHEN array_length(sorted_b,1) > 1 THEN sorted_b[array_length(sorted_b,1)-1] ELSE sorted_b[1] END,
               sorted_b[(array_length(sorted_b,1)+1)/2],
               sorted_b[1]
        INTO max_b, second_b, mid_b, min_b;

        -- 오늘 패턴 계산
        IF current_price > max_b THEN
            pat := '돌파';
        ELSIF current_price > second_b THEN
            pat := '돌파눌림';
        ELSIF current_price > mid_b THEN
            pat := '박스권';
        ELSIF current_price >= min_b THEN
            pat := '이탈';
        ELSE
            pat := '붕괴';
        END IF;

        -- 오늘 pattern 컬럼 갱신
        UPDATE prices
        SET pattern = pat
        WHERE 종목코드 = rec.종목코드
          AND 날짜 = CURRENT_DATE;

    END LOOP; -- 종목 반복
END $$;

-- 3️⃣ stocks 테이블의 pattern 컬럼도 동기화 (최신 패턴으로 업데이트)
UPDATE stocks s
SET pattern = (
    SELECT pattern
    FROM prices
    WHERE 종목코드 = s.종목코드
      AND 날짜 = CURRENT_DATE
    LIMIT 1
)
WHERE EXISTS (
    SELECT 1
    FROM prices
    WHERE 종목코드 = s.종목코드
      AND 날짜 = CURRENT_DATE
      AND pattern IS NOT NULL
);
