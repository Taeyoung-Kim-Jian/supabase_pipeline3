-- 추천 종목 테이블 생성
-- 매일 갱신되는 추천 종목 정보 저장

-- 기존 테이블이 있으면 삭제
DROP TABLE IF EXISTS recommended_stocks;

-- 테이블 생성
CREATE TABLE recommended_stocks (
    id SERIAL PRIMARY KEY,
    추천일 DATE NOT NULL,
    순위 INTEGER NOT NULL,
    종목코드 VARCHAR(20) NOT NULL,
    종목명 VARCHAR(100) NOT NULL,
    돌파일 DATE NOT NULL,
    돌파기간 VARCHAR(10) NOT NULL,
    돌파강도 INTEGER NOT NULL,
    경과일수 INTEGER NOT NULL,
    현재가 DECIMAL(10, 2) NOT NULL,
    고점가격 DECIMAL(10, 2) NOT NULL,
    조정률 DECIMAL(5, 2) NOT NULL,
    "MA20" DECIMAL(10, 2) NOT NULL,
    "MA20근접도" DECIMAL(5, 2) NOT NULL,
    "MA20기울기" DECIMAL(5, 2) NOT NULL,
    패턴 VARCHAR(20) NOT NULL,
    투자점수 INTEGER NOT NULL,
    전고점거리 DECIMAL(5, 2) NOT NULL,
    최근변동성 DECIMAL(5, 2),
    종합점수 DECIMAL(6, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- 제약 조건
    CONSTRAINT unique_daily_recommendation UNIQUE (추천일, 종목코드)
);

-- 인덱스 생성
CREATE INDEX idx_recommended_stocks_date ON recommended_stocks(추천일 DESC);
CREATE INDEX idx_recommended_stocks_code ON recommended_stocks(종목코드);
CREATE INDEX idx_recommended_stocks_rank ON recommended_stocks(추천일, 순위);

-- 코멘트 추가
COMMENT ON TABLE recommended_stocks IS '일일 추천 종목 테이블';
COMMENT ON COLUMN recommended_stocks.추천일 IS '추천 날짜';
COMMENT ON COLUMN recommended_stocks.순위 IS '추천 순위 (1~5)';
COMMENT ON COLUMN recommended_stocks.종합점수 IS '종합 추천 점수 (0~100)';
COMMENT ON COLUMN recommended_stocks.돌파강도 IS '신고가 돌파 강도 (1=1년, 5=5년)';
COMMENT ON COLUMN recommended_stocks.조정률 IS '고점 대비 조정률 (%)';
COMMENT ON COLUMN recommended_stocks."MA20근접도" IS '20일선 대비 현재가 위치 (%)';
COMMENT ON COLUMN recommended_stocks."MA20기울기" IS '20일선 기울기 (5일 전 대비 %)';
COMMENT ON COLUMN recommended_stocks.전고점거리 IS '전고점까지 상승 여력 (%)';

-- Row Level Security 설정 (선택사항)
ALTER TABLE recommended_stocks ENABLE ROW LEVEL SECURITY;

-- 모든 사용자 읽기 허용
CREATE POLICY "Allow public read access"
ON recommended_stocks
FOR SELECT
USING (true);

-- 서비스 롤만 쓰기 허용
CREATE POLICY "Allow service role full access"
ON recommended_stocks
FOR ALL
USING (auth.role() = 'service_role');
