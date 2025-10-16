const { createClient } = require('@supabase/supabase-js');

// Supabase 클라이언트 생성
const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_KEY;

if (!supabaseUrl || !supabaseKey) {
  console.error('❌ SUPABASE_URL 또는 SUPABASE_KEY 환경 변수가 설정되지 않았습니다.');
  process.exit(1);
}

const supabase = createClient(supabaseUrl, supabaseKey);

async function updatePatterns() {
  console.log('🚀 가격 패턴 업데이트 시작...');
  console.log(`📅 실행 시간: ${new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })}`);
  
  try {
    // Supabase 함수 호출
    const { data, error } = await supabase.rpc('update_price_patterns');
    
    if (error) {
      console.error('❌ 오류 발생:', error);
      process.exit(1);
    }
    
    console.log('✅ 업데이트 완료!');
    console.log('📊 결과:', JSON.stringify(data, null, 2));
    
  } catch (err) {
    console.error('❌ 예외 발생:', err);
    process.exit(1);
  }
}

// 함수 실행
updatePatterns();
