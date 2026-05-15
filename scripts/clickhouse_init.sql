-- ClickHouse initial schema for the analytics workload.
--
-- This file is bind-mounted to /docker-entrypoint-initdb.d/init.sql
-- in compose; the official clickhouse-server image runs anything
-- in that directory once, on first boot when the data dir is empty.
-- Every CREATE uses IF NOT EXISTS so re-runs (e.g. via clickhouse-client
-- against a live container) are also idempotent.
--
-- Why ClickHouse and not Postgres for this data:
--   * Append-only event stream that can grow into the millions per
--     flash sale; row-store Postgres pays an index-maintenance cost
--     for every insert.
--   * Aggregations (`SELECT action, count(), sum(quantity) GROUP BY ...`)
--     scan whole partitions sequentially in ClickHouse — sub-100ms
--     against millions of rows. The same query in Postgres needs a
--     covering index per axis.
--   * Time-series ergonomics: toStartOfMinute / partition pruning by
--     month are first-class here.

CREATE DATABASE IF NOT EXISTS analytics;

-- ----------------------- flash_sale_events ------------------------
-- One row per intent / accept / reject for a flash-sale variant.
-- LowCardinality(String) on action/rejection_reason gives us small
-- dictionaries (cheap to filter, cheap to GROUP BY).
-- Partition by month so old data can be dropped quickly; TTL drops
-- rows older than 90 days automatically.
CREATE TABLE IF NOT EXISTS analytics.flash_sale_events (
    event_time DateTime64(3, 'UTC'),
    flash_sale_id UInt64,
    variant_id UInt64,
    user_id UInt64,
    action LowCardinality(String),       -- 'attempt' | 'accepted' | 'rejected'
    quantity Int32,
    latency_ms UInt32,
    rejection_reason LowCardinality(String) DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_time)
ORDER BY (flash_sale_id, event_time, user_id)
TTL toDateTime(event_time) + INTERVAL 90 DAY;

-- ----------------------- order_events ------------------------
-- One row per order status transition (pending → paid → fulfilling
-- → cancelled). Used by daily settlement and the admin dashboard.
CREATE TABLE IF NOT EXISTS analytics.order_events (
    event_time DateTime64(3, 'UTC'),
    order_id UInt64,
    user_id UInt64,
    status LowCardinality(String),
    total Decimal(12, 2),
    item_count UInt16
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, user_id)
TTL toDateTime(event_time) + INTERVAL 365 DAY;

-- ----------------------- flash_sale_minute_stats (MV) ------------------------
-- Pre-aggregates flash_sale_events at insert time so per-minute
-- queries don't scan the raw event stream. SummingMergeTree merges
-- rows that share the ORDER BY key in the background.
--
-- IMPORTANT: queries against this view must still wrap numeric
-- columns in sum() — between background merges a key can have
-- multiple unmerged rows.
CREATE MATERIALIZED VIEW IF NOT EXISTS analytics.flash_sale_minute_stats
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(minute)
ORDER BY (flash_sale_id, minute, action)
AS SELECT
    flash_sale_id,
    toStartOfMinute(event_time) AS minute,
    action,
    count() AS event_count,
    sum(quantity) AS total_quantity
FROM analytics.flash_sale_events
GROUP BY flash_sale_id, minute, action;
