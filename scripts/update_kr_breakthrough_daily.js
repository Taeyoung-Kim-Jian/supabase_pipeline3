const { Pool } = require('pg');
const dns = require('dns');
dns.setDefaultResultOrder('ipv4first');
require('dotenv').config();

process.env.TZ = process.env.TZ || 'Asia/Seoul';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: process.env.DATABASE_URL?.includes('supabase.co') ? { rejectUnauthorized: false } : false
});
const KST_TIME_ZONE = 'Asia/Seoul';

function toKstDateString(value) {
  if (!value) return null;
  if (typeof value === 'string') return value.substring(0, 10);

  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).substring(0, 10);

  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: KST_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(date).reduce((acc, part) => {
    if (part.type !== 'literal') acc[part.type] = part.value;
    return acc;
  }, {});

  return `${parts.year}-${parts.month}-${parts.day}`;
}

function normalizePriceRows(rows = []) {
  return rows.map(row => ({
    rawDate: row.날짜,
    dateStr: toKstDateString(row.날짜),
    종가: Number(row.종가) || 0,
    고가: Number(row.고가) || 0,
    저가: Number(row.저가) || 0
  }));
}

function computePostBreakthroughStats(priceData, breakthroughDate, breakoutPrice) {
  const breakoutDateStr = toKstDateString(breakthroughDate);
  const 기준가 = Number(breakoutPrice);

  if (!breakoutDateStr || !(기준가 > 0)) {
    return { maxReturn: null, minReturn: null };
  }

  const afterData = priceData.filter(row => row.dateStr && row.dateStr >= breakoutDateStr);
  if (afterData.length === 0) {
    return { maxReturn: null, minReturn: null };
  }

  const validHighs = afterData.map(row => row.고가).filter(value => value > 0);
  const validLows = afterData.map(row => row.저가).filter(value => value > 0);

  return {
    maxReturn: validHighs.length > 0 ? ((Math.max(...validHighs) - 기준가) / 기준가 * 100) : null,
    minReturn: validLows.length > 0 ? ((Math.min(...validLows) - 기준가) / 기준가 * 100) : null
  };
}

async function refreshExistingBreakthroughMetrics(stockCode, priceData, latestPrice) {
  const historyRows = await pool.query(`
    SELECT 기준일, 현재가,
           돌파일_1년, 돌파가_1년, 돌파후최고수익률_1년, 돌파후최저수익률_1년,
           돌파일_2년, 돌파가_2년, 돌파후최고수익률_2년, 돌파후최저수익률_2년,
           돌파일_3년, 돌파가_3년, 돌파후최고수익률_3년, 돌파후최저수익률_3년,
           돌파일_4년, 돌파가_4년, 돌파후최고수익률_4년, 돌파후최저수익률_4년,
           돌파일_5년, 돌파가_5년, 돌파후최고수익률_5년, 돌파후최저수익률_5년
    FROM kr_breakthrough_history
    WHERE 종목코드 = $1
      AND 기준일 >= CURRENT_DATE - INTERVAL '24 months'
  `, [stockCode]);

  let refreshed = 0;

  for (const row of historyRows.rows) {
    const updateAssignments = [];
    const params = [];
    let paramIndex = 1;

    const storedCurrentPrice = Number(row.현재가);
    if (!Number.isFinite(storedCurrentPrice) || Math.abs(storedCurrentPrice - Number(latestPrice)) > 1e-9) {
      updateAssignments.push(`"현재가" = $${paramIndex++}`);
      params.push(latestPrice);
    }

    for (const period of [1, 2, 3, 4, 5]) {
      const breakoutDate = row[`돌파일_${period}년`];
      const breakoutPrice = row[`돌파가_${period}년`];
      if (!breakoutDate || !(Number(breakoutPrice) > 0)) continue;

      const { maxReturn, minReturn } = computePostBreakthroughStats(priceData, breakoutDate, breakoutPrice);
      const storedMax = row[`돌파후최고수익률_${period}년`];
      const storedMin = row[`돌파후최저수익률_${period}년`];
      const storedMaxNum = storedMax == null ? null : Number(storedMax);
      const storedMinNum = storedMin == null ? null : Number(storedMin);

      if (maxReturn !== null && (storedMaxNum === null || !Number.isFinite(storedMaxNum) || Math.abs(storedMaxNum - maxReturn) > 1e-9)) {
        updateAssignments.push(`"돌파후최고수익률_${period}년" = $${paramIndex++}`);
        params.push(maxReturn);
      }

      if (minReturn !== null && (storedMinNum === null || !Number.isFinite(storedMinNum) || Math.abs(storedMinNum - minReturn) > 1e-9)) {
        updateAssignments.push(`"돌파후최저수익률_${period}년" = $${paramIndex++}`);
        params.push(minReturn);
      }
    }

    if (updateAssignments.length === 0) continue;

    const stockParamIndex = paramIndex++;
    const dateParamIndex = paramIndex;
    params.push(stockCode, row.기준일);

    await pool.query(`
      UPDATE kr_breakthrough_history
      SET ${updateAssignments.join(', ')}
      WHERE "종목코드" = $${stockParamIndex}
        AND "기준일" = $${dateParamIndex}
    `, params);

    refreshed++;
  }

  return refreshed;
}

async function updateBreakthroughDaily() {
  try {
    console.log('=== 신고가 돌파 이력 일일 업데이트 ===\n');

    // 1. kr_breakthrough_history에서 가장 최근 기준일 조회
    const lastDateResult = await pool.query(`
      SELECT MAX("기준일") as last_date
      FROM kr_breakthrough_history
    `);
    const lastDate = lastDateResult.rows[0]?.last_date;
    console.log(`마지막 업데이트 기준일: ${lastDate || '없음'}`);

    // 2. prices 테이블에서 마지막 업데이트 이후 새로운 거래일 조회
    const newDatesResult = await pool.query(`
      SELECT DISTINCT 날짜
      FROM prices
      WHERE 날짜 > $1
      ORDER BY 날짜 ASC
    `, [lastDate || '2021-01-01']);

    const newDates = newDatesResult.rows.map(r => r.날짜);
    const newDateStrings = new Set(newDates.map(toKstDateString).filter(Boolean));

    if (newDates.length === 0) {
      console.log('새로운 거래일이 없습니다. 기존 돌파 수익률을 최신 prices 기준으로 동기화합니다.\n');
    } else {
      console.log(`새로운 거래일 ${newDates.length}개 발견: ${toKstDateString(newDates[0])} ~ ${toKstDateString(newDates[newDates.length - 1])}\n`);
    }

    // 3. 모든 종목 조회
    const stocks = await pool.query(`
      SELECT DISTINCT 종목코드
      FROM prices
      WHERE 날짜 >= '2021-01-01'
      ORDER BY 종목코드
    `);

    console.log(`총 ${stocks.rows.length}개 종목 분석 시작...\n`);

    let processedCount = 0;
    let totalInserted = 0;
    let totalRefreshed = 0;

    for (const stock of stocks.rows) {
      processedCount++;

      if (processedCount % 50 === 0) {
        console.log(`진행 중: ${processedCount}/${stocks.rows.length} (${(processedCount / stocks.rows.length * 100).toFixed(1)}%) - 삽입: ${totalInserted}개`);
      }

      // 종목명 조회
      const stockInfo = await pool.query(`
        SELECT 종목명
        FROM prices
        WHERE 종목코드 = $1
        LIMIT 1
      `, [stock.종목코드]);

      const 종목명 = stockInfo.rows[0]?.종목명 || stock.종목코드;

      // 해당 종목의 모든 주가 데이터 조회 (5년 계산을 위해 충분한 과거 데이터 포함)
      const prices = await pool.query(`
        SELECT 날짜, 종가, 고가, 저가
        FROM prices
        WHERE 종목코드 = $1
          AND 날짜 >= '2020-01-01'
        ORDER BY 날짜 ASC
      `, [stock.종목코드]);

      if (prices.rows.length < 250) continue;

      const priceData = normalizePriceRows(prices.rows);
      const breakthroughRecords = [];

      // 가장 최근 종가 (현재가)
      const 최근가격 = priceData[priceData.length - 1]?.종가 || 0;

      // 새로운 거래일이 있을 때만 신규 레코드 생성
      if (newDateStrings.size > 0) {
        for (let i = 0; i < priceData.length; i++) {
          const today = priceData[i];
          const 날짜 = today.rawDate;

          // 새로운 거래일에 해당하지 않으면 스킵
          const isNewDate = newDateStrings.has(today.dateStr);
          if (!isNewDate) continue;

          const breakthroughData = {
            종목코드: stock.종목코드,
            종목명: 종목명,
            현재가: 최근가격,
            기준일: 날짜
          };

          let hasBreakthrough = false;

          // 각 기간별 신고가 확인
          for (const period of [1, 2, 3, 4, 5]) {
            const periodDays = period * 252;

            if (i < periodDays) continue;

            // 과거 N년간 최고가 찾기
            const pastData = priceData.slice(Math.max(0, i - periodDays), i);
            if (pastData.length === 0) continue;

            const 저항가 = Math.max(...pastData.map(p => p.고가 || 0));

            // 신고가 돌파 확인
            if (today.고가 > 저항가) {
              const 돌파가 = today.종가;

              breakthroughData[`저항가_${period}년`] = 저항가;
              breakthroughData[`돌파일_${period}년`] = 날짜;
              breakthroughData[`돌파가_${period}년`] = 돌파가;

              const { maxReturn, minReturn } = computePostBreakthroughStats(priceData, today.dateStr, 돌파가);
              if (maxReturn !== null) {
                breakthroughData[`돌파후최고수익률_${period}년`] = maxReturn;
              }
              if (minReturn !== null) {
                breakthroughData[`돌파후최저수익률_${period}년`] = minReturn;
              }

              hasBreakthrough = true;
            }
          }

          if (hasBreakthrough) {
            breakthroughRecords.push(breakthroughData);
          }
        }
      }

      // UPSERT로 저장
      if (breakthroughRecords.length > 0) {
        for (const record of breakthroughRecords) {
          try {
            const columns = Object.keys(record);
            const values = Object.values(record);
            const placeholders = values.map((_, i) => `$${i + 1}`).join(', ');

            const updateCols = columns.slice(2).map(col => `"${col}" = EXCLUDED."${col}"`).join(', ');
            const quotedCols = columns.map(col => `"${col}"`).join(', ');

            await pool.query(`
              INSERT INTO kr_breakthrough_history (${quotedCols})
              VALUES (${placeholders})
              ON CONFLICT ("종목코드", "기준일") DO UPDATE SET ${updateCols}
            `, values);

            totalInserted++;
          } catch (err) {
            console.error(`삽입 오류 (${종목명}, ${record.기준일}):`, err.message);
          }
        }
      }

      const refreshedCount = await refreshExistingBreakthroughMetrics(stock.종목코드, priceData, 최근가격);
      totalRefreshed += refreshedCount;
    }

    console.log(`\n완료!`);
    console.log(`총 처리 종목: ${processedCount}개`);
    console.log(`새로 저장된 레코드: ${totalInserted}개`);
    console.log(`최신 prices 기준으로 갱신된 레코드: ${totalRefreshed}개`);
    console.log(`처리된 거래일: ${newDates.length}일`);

  } catch (error) {
    console.error('Error:', error.message);
    console.error(error.stack);
    process.exit(1);
  } finally {
    await pool.end();
  }
}

updateBreakthroughDaily();
