/*
 * Complete one-minute dataset query for grid-strategy research.
 * Start with FPT for one full day, then expand by complete calendar months.
 */
WITH settings AS (
    SELECT
        TIMESTAMP '2026-07-15 00:00:00' AS start_time,
        TIMESTAMP '2026-07-16 00:00:00' AS end_time
),

selected_tickers(tickersymbol) AS (
    VALUES ('FPT')
),

/*
 * During continuous trading, each matchedvolume row is an incremental
 * matched amount. Auction values have different semantics and are excluded
 * from the final minute bars below.
 */
volume_base AS (
    SELECT
        mv.datetime AS event_time,
        DATE(mv.datetime) AS trading_date,
        mv.tickersymbol,
        mv.quantity::numeric AS matched_quantity_event
    FROM quote.matchedvolume mv
    INNER JOIN selected_tickers st
        ON st.tickersymbol = mv.tickersymbol
    CROSS JOIN settings cfg
    WHERE mv.datetime >= cfg.start_time
      AND mv.datetime <  cfg.end_time
),

matched_events AS (
    SELECT
        event_time,
        trading_date,
        tickersymbol,
        matched_quantity_event,
        CASE
            WHEN event_time::time >= TIME '09:00:00'
             AND event_time::time <  TIME '09:15:00'
                THEN 'opening_auction'
            WHEN event_time::time >= TIME '09:15:00'
             AND event_time::time <  TIME '11:30:00'
                THEN 'continuous_morning'
            WHEN event_time::time >= TIME '13:00:00'
             AND event_time::time <  TIME '14:30:00'
                THEN 'continuous_afternoon'
            WHEN event_time::time >= TIME '14:30:00'
             AND event_time::time <  TIME '14:45:00'
                THEN 'closing_auction'
            ELSE 'outside_standard_session'
        END AS market_session
    FROM volume_base
),

valid_quantity_events AS (
    SELECT *
    FROM matched_events
    WHERE matched_quantity_event > 0
),

/* Attach the latest known matched price and level-one book state. */
market_state AS (
    SELECT
        e.event_time,
        e.trading_date,
        e.tickersymbol,
        e.market_session,
        mp.price::numeric AS matched_price,
        e.matched_quantity_event,
        bp.price::numeric AS best_bid_price,
        bs.quantity::numeric AS best_bid_quantity,
        ap.price::numeric AS best_ask_price,
        az.quantity::numeric AS best_ask_quantity
    FROM valid_quantity_events e

    LEFT JOIN LATERAL (
        SELECT p.price
        FROM quote.matched p
        WHERE p.tickersymbol = e.tickersymbol
          AND p.datetime <= e.event_time
          AND p.datetime >= DATE_TRUNC('day', e.event_time)
        ORDER BY p.datetime DESC
        LIMIT 1
    ) mp ON TRUE

    LEFT JOIN LATERAL (
        SELECT p.price
        FROM quote.bidprice p
        WHERE p.tickersymbol = e.tickersymbol
          AND p.depth = 1
          AND p.datetime <= e.event_time
          AND p.datetime >= DATE_TRUNC('day', e.event_time)
        ORDER BY p.datetime DESC
        LIMIT 1
    ) bp ON TRUE

    LEFT JOIN LATERAL (
        SELECT s.quantity
        FROM quote.bidsize s
        WHERE s.tickersymbol = e.tickersymbol
          AND s.depth = 1
          AND s.datetime <= e.event_time
          AND s.datetime >= DATE_TRUNC('day', e.event_time)
        ORDER BY s.datetime DESC
        LIMIT 1
    ) bs ON TRUE

    LEFT JOIN LATERAL (
        SELECT p.price
        FROM quote.askprice p
        WHERE p.tickersymbol = e.tickersymbol
          AND p.depth = 1
          AND p.datetime <= e.event_time
          AND p.datetime >= DATE_TRUNC('day', e.event_time)
        ORDER BY p.datetime DESC
        LIMIT 1
    ) ap ON TRUE

    LEFT JOIN LATERAL (
        SELECT s.quantity
        FROM quote.asksize s
        WHERE s.tickersymbol = e.tickersymbol
          AND s.depth = 1
          AND s.datetime <= e.event_time
          AND s.datetime >= DATE_TRUNC('day', e.event_time)
        ORDER BY s.datetime DESC
        LIMIT 1
    ) az ON TRUE
),

tick_events AS (
    SELECT
        event_time,
        trading_date,
        tickersymbol,
        market_session,
        matched_price,
        matched_quantity_event,
        best_bid_price,
        best_bid_quantity,
        best_ask_price,
        best_ask_quantity,
        CASE
            WHEN best_bid_price > 0
             AND best_ask_price > 0
             AND best_bid_price + best_ask_price > 0
            THEN
                10000.0
                * (best_ask_price - best_bid_price)
                / ((best_ask_price + best_bid_price) / 2.0)
            ELSE NULL
        END AS spread_bps,
        (
            matched_price IS NOT NULL
            AND matched_quantity_event > 0
            AND best_bid_price IS NOT NULL
            AND best_ask_price IS NOT NULL
            AND best_bid_price <= best_ask_price
        ) AS market_state_valid
    FROM market_state
),

minute_bars AS (
    SELECT
        DATE_TRUNC('minute', event_time) AS minute,
        trading_date,
        tickersymbol,
        market_session,
        (
            ARRAY_AGG(matched_price ORDER BY event_time)
            FILTER (WHERE matched_price IS NOT NULL)
        )[1] AS matched_open,
        MAX(matched_price) AS matched_high,
        MIN(matched_price) AS matched_low,
        (
            ARRAY_AGG(matched_price ORDER BY event_time DESC)
            FILTER (WHERE matched_price IS NOT NULL)
        )[1] AS matched_close,
        SUM(matched_quantity_event) AS matched_quantity,
        (
            ARRAY_AGG(best_bid_price ORDER BY event_time DESC)
            FILTER (WHERE best_bid_price IS NOT NULL)
        )[1] AS last_best_bid,
        (
            ARRAY_AGG(best_bid_quantity ORDER BY event_time DESC)
            FILTER (WHERE best_bid_quantity IS NOT NULL)
        )[1] AS last_best_bid_quantity,
        (
            ARRAY_AGG(best_ask_price ORDER BY event_time DESC)
            FILTER (WHERE best_ask_price IS NOT NULL)
        )[1] AS last_best_ask,
        (
            ARRAY_AGG(best_ask_quantity ORDER BY event_time DESC)
            FILTER (WHERE best_ask_quantity IS NOT NULL)
        )[1] AS last_best_ask_quantity,
        AVG(spread_bps) FILTER (
            WHERE market_state_valid
        ) AS average_spread_bps,
        COUNT(*) AS event_count,
        ROUND(
            100.0
            * COUNT(*) FILTER (WHERE market_state_valid)
            / NULLIF(COUNT(*), 0),
            2
        ) AS valid_event_percentage
    FROM tick_events
    WHERE market_session IN (
        'continuous_morning',
        'continuous_afternoon'
    )
    GROUP BY
        DATE_TRUNC('minute', event_time),
        trading_date,
        tickersymbol,
        market_session
)

SELECT
    minute,
    trading_date,
    tickersymbol,
    market_session,
    matched_open,
    matched_high,
    matched_low,
    matched_close,
    matched_quantity,
    last_best_bid,
    last_best_bid_quantity,
    last_best_ask,
    last_best_ask_quantity,
    average_spread_bps,
    event_count,
    valid_event_percentage
FROM minute_bars
ORDER BY tickersymbol, minute;
