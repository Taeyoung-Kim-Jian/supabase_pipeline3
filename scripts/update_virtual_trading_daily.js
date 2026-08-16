// 가상매매(페이퍼 트레이딩) 일일 업데이트
// 전략: 3년+ 신고가 돌파 + 돌파전 필터(60일 상승폭<80%, 돌파일 거래량스파이크<6배) + day10 양전 확인
//       -> day10 종가로 조건만 판정, 실제 매수는 day11(다음 거래일) 시가에 체결 -> day20에 모멘텀 강도 판정
//       -> 강한모멘텀(day20 수익률>=15%): -30%손절 + 사다리(+50/80/150/300%) + 300%이후 고점대비-25%추적손절, 시간제한 없음
//       -> 약한모멘텀: -30%손절 + 사다리(+80%->+40%락) + 120거래일 캡
const { Pool } = require('pg');
const dns = require('dns');
dns.setDefaultResultOrder('ipv4first');
require('dotenv').config();

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: process.env.DATABASE_URL?.includes('supabase.co') ? { rejectUnauthorized: false } : false
});

const INVEST_PER_STOCK = 10_000_000;
const BASE_STOP = -0.30;
const PRE_FILTER_VOL_SPIKE_MAX = 6.0;
const PRE_FILTER_PRE60_TREND_MAX = 0.80;
const STRONG_MOMENTUM_THRESHOLD = 0.15;
const WEAK_HOLD_DAYS_CAP = 120;
const STRONG_LADDER = [[0.5, 0.2], [0.8, 0.4], [1.5, 1.0], [3.0, 2.0]];
const WEAK_LADDER = [[0.8, 0.4]];
const TRAIL_AFTER = 3.0;
const TRAIL_PCT = 0.25;

const priceCache = new Map();

async function getPriceSeries(code) {
  if (priceCache.has(code)) return priceCache.get(code);
  const r = await pool.query(`
    SELECT 날짜 AS date, 종가::float AS close, 시가::float AS open, 고가::float AS high, 저가::float AS low, 거래량::float AS volume
    FROM prices WHERE 종목코드 = $1 ORDER BY 날짜 ASC
  `, [code]);
  const rows = r.rows.map(row => ({
    date: row.date.toISOString().slice(0, 10),
    close: row.close, open: row.open, high: row.high, low: row.low, volume: row.volume || 0
  }));
  priceCache.set(code, rows);
  return rows;
}

function findIndexByDate(series, dateStr) {
  return series.findIndex(r => r.date === dateStr);
}

function computeLadderStop(entryPrice, peakGain, ladder) {
  let stop = entryPrice * (1 + BASE_STOP);
  for (const [thresh, lock] of ladder) {
    if (peakGain >= thresh) stop = Math.max(stop, entryPrice * (1 + lock));
  }
  return stop;
}

// ── 1) 진입 스캔: 신규 day10 확인 신호를 찾아 가상매수 ──
async function scanNewEntries() {
  console.log('\n=== 1) 진입 스캔 ===');
  const stocksResult = await pool.query(`SELECT DISTINCT 종목코드 FROM prices`);
  let inserted = 0;

  for (const { 종목코드: code } of stocksResult.rows) {
    const series = await getPriceSeries(code);
    if (series.length < 70) continue;

    const btResult = await pool.query(`
      SELECT 종목명,
             돌파일_3년, 돌파가_3년, 돌파일_4년, 돌파가_4년, 돌파일_5년, 돌파가_5년
      FROM kr_breakthrough_history
      WHERE 종목코드 = $1
      ORDER BY 기준일 DESC LIMIT 1
    `, [code]);
    if (btResult.rows.length === 0) continue;
    const row = btResult.rows[0];
    const name = row.종목명 || code;

    // 3/4/5년 중 존재하는 가장 큰 연수 하나만 사용(중복 방지)
    let years = null, breakoutDate = null, breakoutPrice = null;
    for (const y of [5, 4, 3]) {
      const bd = row[`돌파일_${y}년`];
      const bp = row[`돌파가_${y}년`];
      if (bd && bp) { years = y; breakoutDate = bd.toISOString().slice(0, 10); breakoutPrice = Number(bp); break; }
    }
    if (!breakoutDate) continue;

    const i0 = findIndexByDate(series, breakoutDate);
    if (i0 < 60) continue;
    const day10Idx = i0 + 10;
    const buyIdx = i0 + 11; // 매수는 day10 확인 다음 거래일(day11) 시가에 체결
    if (buyIdx >= series.length) continue; // 아직 매수시점 도달 전

    const day10Row = series[day10Idx];
    const ret10 = day10Row.close / breakoutPrice - 1;
    if (ret10 <= 0) continue; // day10 확인 실패

    // 이미 매수한 적 있는지(종목코드+돌파일 유니크) 확인
    const exists = await pool.query(
      `SELECT 1 FROM virtual_trades WHERE 종목코드=$1 AND breakout_date=$2`, [code, breakoutDate]
    );
    if (exists.rows.length > 0) continue;

    // 매수시점(day11)이 "오늘" 발생한 것인지 확인 (과거 신호를 소급 매수하지 않음)
    const buyRow = series[buyIdx];
    const latestDate = series[series.length - 1].date;
    if (buyRow.date !== latestDate) continue;

    // 돌파전 필터 계산
    const pre60 = series.slice(i0 - 60, i0);
    const pre60Trend = series[i0 - 1].close / series[i0 - 60].close - 1;
    const pre60VolAvg = pre60.reduce((s, r) => s + r.volume, 0) / pre60.length;
    const volSpike = pre60VolAvg > 0 ? series[i0].volume / pre60VolAvg : null;
    const passesFilter = volSpike !== null &&
      volSpike < PRE_FILTER_VOL_SPIKE_MAX && pre60Trend < PRE_FILTER_PRE60_TREND_MAX;

    if (!passesFilter) {
      console.log(`  [필터탈락] ${name}(${code}) volSpike=${volSpike?.toFixed(2)} pre60Trend=${(pre60Trend*100).toFixed(1)}%`);
      continue;
    }

    const buyPrice = buyRow.open;
    const quantity = Math.floor(INVEST_PER_STOCK / buyPrice);
    if (quantity <= 0) continue;
    const invested = quantity * buyPrice;
    const stopPrice = buyPrice * (1 + BASE_STOP);

    await pool.query(`
      INSERT INTO virtual_trades
        (종목코드, 종목명, breakout_date, breakout_price, years, buy_date, buy_price, quantity, invested_amount,
         passed_pre_filter, pre60_trend, breakout_vol_spike,
         status, day20_checked, peak_price, stop_price, current_price, current_date_checked, updated_at)
      VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'open',false,$7,$13,$7,$6, now())
    `, [code, name, breakoutDate, breakoutPrice, years, buyRow.date, buyPrice, quantity, invested,
        passesFilter, pre60Trend, volSpike, stopPrice]);

    console.log(`  [신규매수] ${name}(${code}) ${buyRow.date} 시가매수가=${buyPrice} 수량=${quantity} 투자금=${invested}`);
    inserted++;
  }
  console.log(`진입 스캔 완료: ${inserted}건 신규매수`);
}

// ── 2) day20 모멘텀 판정 ──
async function classifyDay20() {
  console.log('\n=== 2) day20 모멘텀 판정 ===');
  const openPositions = await pool.query(`
    SELECT id, 종목코드, breakout_date, breakout_price FROM virtual_trades
    WHERE status='open' AND day20_checked=false
  `);
  let classified = 0;

  for (const pos of openPositions.rows) {
    const series = await getPriceSeries(pos.종목코드);
    const breakoutDate = pos.breakout_date.toISOString().slice(0, 10);
    const i0 = findIndexByDate(series, breakoutDate);
    if (i0 < 0) continue;
    const day20Idx = i0 + 20;
    if (day20Idx >= series.length) continue; // 아직 day20 미도달

    const ret20 = series[day20Idx].close / Number(pos.breakout_price) - 1;
    const isStrong = ret20 >= STRONG_MOMENTUM_THRESHOLD;

    await pool.query(`
      UPDATE virtual_trades SET day20_checked=true, is_strong_momentum=$1, ret_20d=$2, updated_at=now()
      WHERE id=$3
    `, [isStrong, ret20, pos.id]);

    console.log(`  [day20판정] ${pos.종목코드} ret20=${(ret20*100).toFixed(1)}% -> ${isStrong ? '강한모멘텀(장기보유)' : '약한모멘텀(120일캡)'}`);
    classified++;
  }
  console.log(`day20 판정 완료: ${classified}건`);
}

// ── 3) 보유 포지션 일일 손절/청산 관리 ──
async function manageOpenPositions() {
  console.log('\n=== 3) 보유 포지션 관리 ===');
  const openPositions = await pool.query(`
    SELECT * FROM virtual_trades WHERE status='open'
  `);
  let closedCount = 0, updatedCount = 0;

  for (const pos of openPositions.rows) {
    const series = await getPriceSeries(pos.종목코드);
    const buyDate = pos.buy_date.toISOString().slice(0, 10);
    const buyIdx = findIndexByDate(series, buyDate);
    if (buyIdx < 0) continue;
    const lastCheckedDate = pos.current_date_checked ? pos.current_date_checked.toISOString().slice(0, 10) : buyDate;
    const lastCheckedIdx = findIndexByDate(series, lastCheckedDate);
    const startIdx = Math.max(lastCheckedIdx, buyIdx) + 1;

    let peakPrice = Number(pos.peak_price);
    let stopPrice = Number(pos.stop_price);
    const buyPrice = Number(pos.buy_price);
    let closed = false;

    for (let idx = startIdx; idx < series.length; idx++) {
      const day = series[idx];
      peakPrice = Math.max(peakPrice, day.high);
      const peakGain = peakPrice / buyPrice - 1;

      if (pos.is_strong_momentum === true) {
        if (peakGain >= TRAIL_AFTER) {
          stopPrice = Math.max(stopPrice, buyPrice * (1 + peakGain * (1 - TRAIL_PCT)));
        } else {
          stopPrice = Math.max(stopPrice, computeLadderStop(buyPrice, peakGain, STRONG_LADDER));
        }
      } else {
        stopPrice = Math.max(stopPrice, computeLadderStop(buyPrice, peakGain, WEAK_LADDER));
      }

      if (day.low <= stopPrice) {
        const sellPrice = stopPrice;
        const realizedPnl = (sellPrice - buyPrice) * pos.quantity;
        const realizedPnlPct = sellPrice / buyPrice - 1;
        const holdDays = idx - buyIdx;
        const reason = Math.abs(stopPrice - buyPrice * (1 + BASE_STOP)) < 0.5 ? 'stoploss_-30%'
          : (pos.is_strong_momentum && peakGain >= TRAIL_AFTER ? 'trailing_stop_25%' : 'ladder_lock');
        await pool.query(`
          UPDATE virtual_trades SET status='closed', sell_date=$1, sell_price=$2, sell_reason=$3,
            realized_pnl=$4, realized_pnl_pct=$5, hold_days=$6, peak_price=$7, stop_price=$8,
            current_price=$2, current_date_checked=$1, updated_at=now()
          WHERE id=$9
        `, [day.date, sellPrice, reason, realizedPnl, realizedPnlPct, holdDays, peakPrice, stopPrice, pos.id]);
        console.log(`  [청산] ${pos.종목명}(${pos.종목코드}) ${day.date} 사유=${reason} 수익률=${(realizedPnlPct*100).toFixed(1)}%`);
        closed = true;
        closedCount++;
        break;
      }

      // 약한모멘텀 + day20 판정 완료 + 120거래일 캡 도달 -> 강제청산
      const holdDaysSoFar = idx - buyIdx;
      if (pos.day20_checked && pos.is_strong_momentum === false && holdDaysSoFar >= WEAK_HOLD_DAYS_CAP) {
        const sellPrice = day.close;
        const realizedPnl = (sellPrice - buyPrice) * pos.quantity;
        const realizedPnlPct = sellPrice / buyPrice - 1;
        await pool.query(`
          UPDATE virtual_trades SET status='closed', sell_date=$1, sell_price=$2, sell_reason='time_cap_120d',
            realized_pnl=$3, realized_pnl_pct=$4, hold_days=$5, peak_price=$6, stop_price=$7,
            current_price=$2, current_date_checked=$1, updated_at=now()
          WHERE id=$8
        `, [day.date, sellPrice, realizedPnl, realizedPnlPct, holdDaysSoFar, peakPrice, stopPrice, pos.id]);
        console.log(`  [120일캡청산] ${pos.종목명}(${pos.종목코드}) ${day.date} 수익률=${(realizedPnlPct*100).toFixed(1)}%`);
        closed = true;
        closedCount++;
        break;
      }
    }

    if (!closed && series.length > buyIdx) {
      const last = series[series.length - 1];
      const unrealizedPnl = (last.close - buyPrice) * pos.quantity;
      const unrealizedPnlPct = last.close / buyPrice - 1;
      await pool.query(`
        UPDATE virtual_trades SET peak_price=$1, stop_price=$2, current_price=$3, current_date_checked=$4,
          unrealized_pnl=$5, unrealized_pnl_pct=$6, updated_at=now()
        WHERE id=$7
      `, [peakPrice, stopPrice, last.close, last.date, unrealizedPnl, unrealizedPnlPct, pos.id]);
      updatedCount++;
    }
  }
  console.log(`포지션 관리 완료: ${updatedCount}건 갱신, ${closedCount}건 청산`);
}

async function main() {
  try {
    await scanNewEntries();
    await classifyDay20();
    await manageOpenPositions();
    console.log('\n=== 가상매매 일일 업데이트 완료 ===');
  } catch (err) {
    console.error('Error:', err.message);
    console.error(err.stack);
    process.exit(1);
  } finally {
    await pool.end();
  }
}

main();
