DO $$
DECLARE
    rec RECORD;
    b RECORD;
    b_next RECORD;
    b_prices FLOAT[];
    pat TEXT;
    r RECORD;
    current_price FLOAT;
    sorted_b FLOAT[];
    max_b FLOAT;
    mid_b FLOAT;
    min_b FLOAT;
BEGIN
    FOR rec IN SELECT DISTINCT "종목코드" FROM bt_points LOOP
        FOR b IN 
            SELECT * FROM bt_points 
            WHERE "종목코드" = rec."종목코드" 
            ORDER BY "b날짜"
        LOOP
            SELECT * INTO b_next 
            FROM bt_points 
            WHERE "종목코드" = rec."종목코드" 
              AND "b날짜" > b."b날짜"
            ORDER BY "b날짜" LIMIT 1;

            IF NOT FOUND THEN
                b_next."b날짜" := CURRENT_DATE;
            END IF;

            SELECT ARRAY_AGG("b가격" ORDER BY "b가격")
            INTO b_prices
            FROM bt_points
            WHERE "종목코드" = rec."종목코드";

            FOR r IN
                SELECT "날짜", "종가"
                FROM prices
                WHERE "종목코드" = rec."종목코드"
                  AND "날짜" > b."b날짜"
                  AND "날짜" <= b_next."b날짜"
                  AND "날짜" >= CURRENT_DATE - INTERVAL '1 day'
                ORDER BY "날짜"
            LOOP
                current_price := r."종가";
                IF array_length(b_prices, 1) IS NULL THEN
                    pat := '기타';
                ELSE
                    sorted_b := b_prices;
                    SELECT sorted_b[array_length(sorted_b,1)],
                           sorted_b[(array_length(sorted_b,1)+1)/2],
                           sorted_b[1]
                    INTO max_b, mid_b, min_b;

                    IF current_price > max_b THEN
                        pat := '돌파';
                    ELSIF current_price > mid_b THEN
                        pat := '돌파눌림';
                    ELSIF current_price >= min_b THEN
                        pat := '박스권';
                    ELSE
                        pat := '이탈';
                    END IF;
                END IF;

                INSERT INTO prices ("종목코드", "날짜", "종가", pattern)
                VALUES (rec."종목코드", r."날짜", r."종가", pat)
                ON CONFLICT ("종목코드", "날짜")
                DO UPDATE SET
                    "종가" = EXCLUDED."종가",
                    pattern = EXCLUDED.pattern;
            END LOOP;
        END LOOP;
    END LOOP;
END $$;
