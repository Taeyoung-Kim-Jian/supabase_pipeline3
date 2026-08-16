/**
 * 스윙 패턴 일일 분석 스크립트
 * ================================
 * 매일 장 마감 후 실행 (GitHub Actions)
 *
 * 흐름:
 *   1. kr_breakthrough_history에서 전체 종목 로드
 *   2. prices 테이블에서 가격 데이터 로드
 *   3. 각 종목별로 ZigZag / 패턴 분류 / 전저점 이탈 등 계산
 *   4. 결과를 kr_pattern_analysis 테이블에 UPSERT
 *
 * 웹에서는 kr_pattern_analysis만 조회하면 됨 → 빠른 로딩
 */

const { Pool } = require('pg');
const dns = require('dns');
dns.setDefaultResultOrder('ipv4first');
require('dotenv').config();

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: process.env.DATABASE_URL?.includes('supabase.co') ? { rejectUnauthorized: false } : false
});

/* ─── 날짜 유틸 ─── */
function toDateStr(v) {
  if (!v) return null;
  if (typeof v === 'string') return v.substring(0, 10);
  const d = v instanceof Date ? v : new Date(v);
  if (isNaN(d.getTime())) return String(v).substring(0, 10);
  return d.toISOString().substring(0, 10);
}

function diffDays(a, b) {
  return Math.round((new Date(a) - new Date(b)) / 86400000);
}

/* ─── ZigZag 알고리즘 ─── */
function detectBouncesExtended(prices, minMove = 0.08) {
  if (!prices || prices.length < 5) {
    return { count: 0, inBounce: false, troughs: [], peaks: [], lowTrend: 'flat', highTrend: 'flat', supportBreakCount: 0, ascendingLowsCount: 0 };
  }

  let direction = 'down';
  let refPrice = Number(prices[0].고가) || Number(prices[0].종가) || 0;
  const troughs = [];
  const peaks = [];

  for (let i = 1; i < prices.length; i++) {
    const p = prices[i];
    const low   = Number(p.저가)  || 0;
    const high  = Number(p.고가)  || 0;
    const close = Number(p.종가)  || 0;

    if (direction === 'down') {
      if (low > 0 && low < refPrice) refPrice = low;
      if (refPrice > 0 && close > 0 && (close - refPrice) / refPrice >= minMove) {
        troughs.push(refPrice);
        direction = 'up';
        refPrice = high || close;
      }
    } else {
      if (high > refPrice) refPrice = high;
      if (refPrice > 0 && close > 0 && (close - refPrice) / refPrice <= -minMove) {
        peaks.push(refPrice);
        direction = 'down';
        refPrice = low || close;
      }
    }
  }

  const count = peaks.length;
  const inBounce = direction === 'up';

  function trendOf(arr) {
    if (arr.length < 2) return 'flat';
    let up = 0, dn = 0;
    for (let i = 1; i < arr.length; i++) {
      if (arr[i] > arr[i - 1] * 1.01) up++;
      else if (arr[i] < arr[i - 1] * 0.99) dn++;
    }
    const half = Math.max(1, Math.floor(arr.length / 2));
    if (up > dn && up >= half) return 'up';
    if (dn > up && dn >= half) return 'down';
    return 'flat';
  }

  let supportBreakCount = 0;
  for (let i = 1; i < troughs.length; i++) {
    if (troughs[i] < troughs[i - 1] * 0.99) supportBreakCount++;
  }

  let ascendingLowsCount = 0;
  for (let i = troughs.length - 1; i > 0; i--) {
    if (troughs[i] > troughs[i - 1]) ascendingLowsCount++;
    else break;
  }

  return { count, inBounce, troughs, peaks, lowTrend: trendOf(troughs), highTrend: trendOf(peaks), supportBreakCount, ascendingLowsCount };
}

/* ─── ML 패턴 분류기 ─── */
function classifySwingPattern({ daysSincePeak, depthPct, bounceCount, lowTrend, highTrend, supportBreakCount, ascendingLowsCount, isDone }) {
  // 패턴 4: 박스권 실패 후 대형 조정 → 복귀 (프로텍형)
  if (depthPct < -45 && daysSincePeak >= 200 && ascendingLowsCount >= 3 && lowTrend === 'up') return 4;
  // 패턴 2: 깊은 조정 + 가짜 상승 반복 (제주반도체형)
  if (depthPct < -35 && daysSincePeak >= 120 && bounceCount >= 2 && (lowTrend === 'up' || lowTrend === 'flat') && highTrend === 'up' && supportBreakCount <= 3) return 2;
  // 패턴 1: 고가 놀이 / 얕은 눌림 (미래에셋형)
  if (depthPct >= -30 && daysSincePeak >= 20 && (lowTrend === 'up' || lowTrend === 'flat') && supportBreakCount <= 1) return 1;
  // 패턴 3: 하락 지속 주의
  if ((lowTrend === 'down' && supportBreakCount >= 3) || (depthPct < -40 && supportBreakCount >= 4 && bounceCount <= 1)) return 3;
  // 패턴 5: 다중 신고가 사이클 (대리 탐지)
  if (isDone && bounceCount >= 2 && highTrend === 'up') return 5;
  return 0;
}

const PATTERN_NAMES = {
  0: '미확정', 1: '고가놀이', 2: '깊은조정+가짜', 3: '하락지속', 4: '복귀중', 5: '다중신고가'
};

/* ─── 전저점 이탈 + P1 감지 ─── */
function detectBreakStructure(afterPeak, currentPrice) {
  const MIN_MOVE = 0.08;
  let direction = 'down';
  let refPrice = Number(afterPeak[0]?.고가) || Number(afterPeak[0]?.종가) || 0;
  const troughs = [];
  const zPeaks = [];

  for (let i = 1; i < afterPeak.length; i++) {
    const p = afterPeak[i];
    const low   = Number(p.저가)  || 0;
    const high  = Number(p.고가)  || 0;
    const close = Number(p.종가)  || 0;
    if (direction === 'down') {
      if (low > 0 && low < refPrice) refPrice = low;
      if (refPrice > 0 && close > 0 && (close - refPrice) / refPrice >= MIN_MOVE) {
        troughs.push(refPrice); direction = 'up'; refPrice = high || close;
      }
    } else {
      if (high > refPrice) refPrice = high;
      if (refPrice > 0 && close > 0 && (close - refPrice) / refPrice <= -MIN_MOVE) {
        zPeaks.push(refPrice); direction = 'down'; refPrice = low || close;
      }
    }
  }

  const T1 = troughs[0] || null;
  const P1 = zPeaks[0]  || null;
  const T2 = troughs[1] || null;
  const prevLowBroken  = !!(T1 && T2 && T2 < T1 * 0.99);
  const reversalSignal = !!(prevLowBroken && P1 && currentPrice > P1);

  return { T1, P1, T2, prevLowBroken, reversalSignal };
}

/* ─── 점수 계산 (기존 웹 로직과 동일) ─── */
function calcScore(최고수익률, 최저수익률, 현재수익률, 돌파일, today) {
  const pullback = Math.min(0, 최저수익률);
  const pullbackScore = Math.max(0, 20 - Math.abs(pullback));
  const peakScore     = Math.max(0, Math.min(25, 최고수익률 * 0.25));
  const currentScore  = Math.max(0, Math.min(20, 현재수익률 * 0.2 + 10));
  const age           = diffDays(today, 돌파일);
  const ageScore      = Math.max(0, 15 - Math.floor(age / 15));
  const strengthScore = Math.max(0, Math.min(20, Math.max(0, 최고수익률 - Math.abs(pullback)) * 0.15));
  return pullbackScore + peakScore + currentScore + ageScore + strengthScore;
}

/* ─── 테이블 생성 (없으면) ─── */
async function ensureTable() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS kr_pattern_analysis (
      종목코드        VARCHAR(20)  NOT NULL,
      종목명          VARCHAR(100),
      분석일          DATE         NOT NULL DEFAULT CURRENT_DATE,
      기간            VARCHAR(10),
      돌파일          DATE,
      돌파가          NUMERIC,
      현재가          NUMERIC,
      현재수익률      NUMERIC,
      최고수익률      NUMERIC,
      최저수익률      NUMERIC,
      점수            NUMERIC,
      신고가          NUMERIC,
      신고가일        DATE,
      신고가후경과일  INTEGER,
      낙폭            NUMERIC,
      반등횟수        INTEGER,
      반등중여부      BOOLEAN,
      저점방향        VARCHAR(10),
      반등고점방향    VARCHAR(10),
      전저점이탈횟수  INTEGER,
      상승저점카운트  INTEGER,
      전저점이탈      BOOLEAN,
      p1가격          NUMERIC,
      t2가격          NUMERIC,
      상승재시도      BOOLEAN,
      흐름국면        VARCHAR(20),
      흐름국면라벨    VARCHAR(50),
      ml_pattern      INTEGER,
      ml_pattern_name VARCHAR(30),
      PRIMARY KEY (종목코드, 분석일)
    );
  `);
  // 최신 분석일 조회를 빠르게
  await pool.query(`
    CREATE INDEX IF NOT EXISTS idx_kpa_분석일 ON kr_pattern_analysis (분석일 DESC);
  `).catch(() => {});
  console.log('✅ kr_pattern_analysis 테이블 준비 완료');
}

/* ─── 메인 분석 ─── */
async function runAnalysis() {
  const TODAY = toDateStr(new Date());
  const ONE_YEAR_AGO = toDateStr(new Date(Date.now() - 365 * 86400000));

  console.log(`\n=== 패턴 분석 일일 업데이트: ${TODAY} ===\n`);

  // 1. kr_breakthrough_history 전체 로드
  const histResult = await pool.query(`
    SELECT
      종목코드, 종목명, 현재가,
      돌파일_1년, 돌파가_1년, 돌파후최고수익률_1년, 돌파후최저수익률_1년,
      돌파일_2년, 돌파가_2년, 돌파후최고수익률_2년, 돌파후최저수익률_2년,
      돌파일_3년, 돌파가_3년, 돌파후최고수익률_3년, 돌파후최저수익률_3년,
      돌파일_4년, 돌파가_4년, 돌파후최고수익률_4년, 돌파후최저수익률_4년,
      돌파일_5년, 돌파가_5년, 돌파후최고수익률_5년, 돌파후최저수익률_5년
    FROM kr_breakthrough_history
  `);

  // 2. 후보 추출 (1년 이내 돌파, 종목당 최고점수 1건)
  const candidateMap = {};
  for (const row of histResult.rows) {
    for (let p = 1; p <= 5; p++) {
      const 돌파일 = toDateStr(row[`돌파일_${p}년`]);
      if (!돌파일 || 돌파일 < ONE_YEAR_AGO || 돌파일 > TODAY) continue;
      const 돌파가 = Number(row[`돌파가_${p}년`]);
      if (돌파가 <= 0) continue;

      const 최고 = Number(row[`돌파후최고수익률_${p}년`]) || 0;
      const 최저 = Number(row[`돌파후최저수익률_${p}년`]) || 0;
      const 현재가 = Number(row.현재가) || 0;
      const 현재수익률 = (현재가 - 돌파가) / 돌파가 * 100;
      const score = calcScore(최고, 최저, 현재수익률, 돌파일, TODAY);

      if (!candidateMap[row.종목코드] || candidateMap[row.종목코드].score < score) {
        candidateMap[row.종목코드] = {
          종목코드: row.종목코드, 종목명: row.종목명, 기간: `${p}년`,
          돌파일, 돌파가, 현재가, 현재수익률, 최고수익률: 최고, 최저수익률: 최저, score
        };
      }
    }
  }

  const candidates = Object.values(candidateMap);
  console.log(`후보 종목: ${candidates.length}개`);

  if (candidates.length === 0) {
    console.log('분석할 종목 없음. 종료');
    return;
  }

  // 3. 가격 데이터 배치 로드
  const codes = candidates.map(c => c.종목코드);
  const earliestDate = candidates.map(c => c.돌파일).sort()[0];

  console.log(`prices 로드: ${codes.length}개 종목, ${earliestDate} ~`);

  const priceResult = await pool.query(`
    SELECT 종목코드, 날짜, 고가, 저가, 종가
    FROM prices
    WHERE 종목코드 = ANY($1)
      AND 날짜 >= $2
    ORDER BY 종목코드, 날짜 ASC
  `, [codes, earliestDate]);

  // 종목별 그룹화
  const pricesByCode = {};
  for (const row of priceResult.rows) {
    const code = row.종목코드;
    if (!pricesByCode[code]) pricesByCode[code] = [];
    pricesByCode[code].push({
      날짜: toDateStr(row.날짜),
      고가: Number(row.고가) || 0,
      저가: Number(row.저가) || 0,
      종가: Number(row.종가) || 0,
    });
  }

  console.log(`prices 로드 완료: ${priceResult.rows.length}행`);

  // 4. 종목별 분석 + UPSERT
  let upserted = 0, skipped = 0;

  for (const c of candidates) {
    const prices = pricesByCode[c.종목코드] || [];
    const afterBreakout = prices.filter(p => p.날짜 >= c.돌파일);

    if (afterBreakout.length < 10) { skipped++; continue; }

    // ① 신고가(Peak) 찾기
    let peakIdx = 0, peakPrice = 0;
    for (let i = 0; i < afterBreakout.length; i++) {
      if (afterBreakout[i].고가 > peakPrice) {
        peakPrice = afterBreakout[i].고가;
        peakIdx = i;
      }
    }
    const peakDate = afterBreakout[peakIdx].날짜;
    const daysSincePeak = diffDays(TODAY, peakDate);

    // ② Peak 이후 데이터
    const afterPeak = afterBreakout.slice(peakIdx);

    // ③ 최저점(낙폭)
    let troughPrice = peakPrice;
    for (const p of afterPeak) {
      if (p.저가 > 0 && p.저가 < troughPrice) troughPrice = p.저가;
    }
    const depthPct = peakPrice > 0 ? (troughPrice - peakPrice) / peakPrice * 100 : 0;

    // ④ ZigZag
    const zz = detectBouncesExtended(afterPeak);
    const { count: bounceCount, inBounce, lowTrend, highTrend, supportBreakCount, ascendingLowsCount } = zz;

    // ⑤ 돌파 완료 여부
    const isDone = c.현재가 >= peakPrice * 0.97;

    // ⑥ 흐름 국면
    let phaseKey, phaseLabel;
    if (isDone) {
      phaseKey = 'done';   phaseLabel = '✅ 돌파 완료';
    } else if (inBounce && bounceCount >= 1) {
      phaseKey = 'bounce'; phaseLabel = `🔄 반등 ${bounceCount}차 중`;
    } else if (daysSincePeak >= 60 && daysSincePeak <= 180) {
      phaseKey = 'golden'; phaseLabel = `⭐ 골든존 (${daysSincePeak}일)`;
    } else if (daysSincePeak < 60) {
      phaseKey = 'early';  phaseLabel = `⚡ 초기 하락 (${daysSincePeak}일)`;
    } else {
      phaseKey = 'long';   phaseLabel = `⏳ 장기 조정 (${daysSincePeak}일)`;
    }

    // ⑦ ML 패턴 분류
    const mlType = classifySwingPattern({ daysSincePeak, depthPct, bounceCount, lowTrend, highTrend, supportBreakCount, ascendingLowsCount, isDone });

    // ⑧ 전저점 이탈 / P1 감지
    const bs = detectBreakStructure(afterPeak, c.현재가);

    // ⑨ UPSERT
    await pool.query(`
      INSERT INTO kr_pattern_analysis (
        종목코드, 종목명, 분석일,
        기간, 돌파일, 돌파가, 현재가, 현재수익률, 최고수익률, 최저수익률, 점수,
        신고가, 신고가일, 신고가후경과일, 낙폭,
        반등횟수, 반등중여부, 저점방향, 반등고점방향, 전저점이탈횟수, 상승저점카운트,
        전저점이탈, p1가격, t2가격, 상승재시도,
        흐름국면, 흐름국면라벨, ml_pattern, ml_pattern_name
      ) VALUES (
        $1,$2,$3,
        $4,$5,$6,$7,$8,$9,$10,$11,
        $12,$13,$14,$15,
        $16,$17,$18,$19,$20,$21,
        $22,$23,$24,$25,
        $26,$27,$28,$29
      )
      ON CONFLICT (종목코드, 분석일) DO UPDATE SET
        종목명          = EXCLUDED.종목명,
        기간            = EXCLUDED.기간,
        돌파일          = EXCLUDED.돌파일,
        돌파가          = EXCLUDED.돌파가,
        현재가          = EXCLUDED.현재가,
        현재수익률      = EXCLUDED.현재수익률,
        최고수익률      = EXCLUDED.최고수익률,
        최저수익률      = EXCLUDED.최저수익률,
        점수            = EXCLUDED.점수,
        신고가          = EXCLUDED.신고가,
        신고가일        = EXCLUDED.신고가일,
        신고가후경과일  = EXCLUDED.신고가후경과일,
        낙폭            = EXCLUDED.낙폭,
        반등횟수        = EXCLUDED.반등횟수,
        반등중여부      = EXCLUDED.반등중여부,
        저점방향        = EXCLUDED.저점방향,
        반등고점방향    = EXCLUDED.반등고점방향,
        전저점이탈횟수  = EXCLUDED.전저점이탈횟수,
        상승저점카운트  = EXCLUDED.상승저점카운트,
        전저점이탈      = EXCLUDED.전저점이탈,
        p1가격          = EXCLUDED.p1가격,
        t2가격          = EXCLUDED.t2가격,
        상승재시도      = EXCLUDED.상승재시도,
        흐름국면        = EXCLUDED.흐름국면,
        흐름국면라벨    = EXCLUDED.흐름국면라벨,
        ml_pattern      = EXCLUDED.ml_pattern,
        ml_pattern_name = EXCLUDED.ml_pattern_name
    `, [
      c.종목코드, c.종목명, TODAY,
      c.기간, c.돌파일, c.돌파가, c.현재가,
      Math.round(c.현재수익률 * 100) / 100,
      Math.round(c.최고수익률 * 100) / 100,
      Math.round(c.최저수익률 * 100) / 100,
      Math.round(c.score * 10) / 10,
      Math.round(peakPrice), peakDate, daysSincePeak,
      Math.round(depthPct * 100) / 100,
      bounceCount, inBounce, lowTrend, highTrend, supportBreakCount, ascendingLowsCount,
      bs.prevLowBroken,
      bs.P1 ? Math.round(bs.P1) : null,
      bs.T2 ? Math.round(bs.T2) : null,
      bs.reversalSignal,
      phaseKey, phaseLabel, mlType, PATTERN_NAMES[mlType] || '미확정'
    ]);

    upserted++;

    if (upserted % 30 === 0) process.stdout.write(`  ${upserted}/${candidates.length} 처리 중...\r`);
  }

  console.log(`\n\n✅ 완료: ${upserted}개 UPSERT / ${skipped}개 스킵`);

  // 오래된 분석 결과 정리 (30일 이전 삭제)
  const cleaned = await pool.query(`
    DELETE FROM kr_pattern_analysis
    WHERE 분석일 < CURRENT_DATE - INTERVAL '30 days'
  `);
  if (cleaned.rowCount > 0) console.log(`🧹 오래된 레코드 ${cleaned.rowCount}개 삭제`);

  // 요약
  const summary = await pool.query(`
    SELECT 흐름국면, COUNT(*) as cnt
    FROM kr_pattern_analysis
    WHERE 분석일 = $1
    GROUP BY 흐름국면
    ORDER BY cnt DESC
  `, [TODAY]);

  const mlSummary = await pool.query(`
    SELECT ml_pattern, ml_pattern_name, COUNT(*) as cnt
    FROM kr_pattern_analysis
    WHERE 분석일 = $1
    GROUP BY ml_pattern, ml_pattern_name
    ORDER BY ml_pattern
  `, [TODAY]);

  console.log('\n📊 흐름 국면 분포:');
  for (const r of summary.rows) console.log(`  ${r.흐름국면}: ${r.cnt}개`);

  console.log('\n🤖 ML 패턴 분포:');
  for (const r of mlSummary.rows) console.log(`  패턴${r.ml_pattern}(${r.ml_pattern_name}): ${r.cnt}개`);
}

(async () => {
  try {
    await ensureTable();
    await runAnalysis();
  } catch (err) {
    console.error('❌ 오류:', err.message);
    console.error(err.stack);
    process.exit(1);
  } finally {
    await pool.end();
  }
})();
