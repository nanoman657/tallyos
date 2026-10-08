-- TallyOS PostgreSQL schema.
-- Timestamps are shop-local wall-clock time (TIMESTAMP without time zone):
-- a single-location barbershop books and reports in its own local time.
-- Money is NUMERIC(12,2); the app loads it as Python float (see db.py).

CREATE TABLE IF NOT EXISTS shop (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    name                    TEXT NOT NULL,
    address                 TEXT NOT NULL DEFAULT '',
    open_weekdays           JSONB NOT NULL DEFAULT '[1,2,3,4,5]',  -- Monday = 0
    open_minute             INTEGER NOT NULL DEFAULT 540,          -- 09:00
    close_minute            INTEGER NOT NULL DEFAULT 1020,         -- 17:00
    break_minutes           INTEGER NOT NULL DEFAULT 30,
    monthly_rent            NUMERIC(12,2) NOT NULL DEFAULT 0,
    monthly_software        NUMERIC(12,2) NOT NULL DEFAULT 0,
    card_fee_rate           NUMERIC(6,4) NOT NULL DEFAULT 0.03,
    state_city_tax_rate     NUMERIC(6,4) NOT NULL DEFAULT 0,
    health_insurance_annual NUMERIC(12,2) NOT NULL DEFAULT 0,
    filing_status           TEXT NOT NULL DEFAULT 'head_of_household'
);

CREATE TABLE IF NOT EXISTS staff (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'barber',
    commission_rate NUMERIC(6,4) NOT NULL DEFAULT 0,   -- share of service revenue paid to the barber
    active          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS services (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    price        NUMERIC(12,2) NOT NULL,
    duration_min INTEGER NOT NULL CHECK (duration_min > 0),
    cogs         NUMERIC(12,2) NOT NULL DEFAULT 0,
    active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS ad_campaigns (
    id              SERIAL PRIMARY KEY,
    external_id     TEXT,                              -- Google Ads campaign resource name
    name            TEXT NOT NULL,
    purpose         TEXT NOT NULL DEFAULT 'fill_capacity',
    status          TEXT NOT NULL DEFAULT 'PAUSED',    -- ENABLED | PAUSED | REMOVED
    daily_budget    NUMERIC(12,2) NOT NULL,
    target_weekdays JSONB NOT NULL DEFAULT '[]',       -- ad schedule, Monday = 0
    headlines       JSONB NOT NULL DEFAULT '[]',
    descriptions    JSONB NOT NULL DEFAULT '[]',
    keywords        JSONB NOT NULL DEFAULT '[]',
    managed_by_loop BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    updated_at      TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clients (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    phone       TEXT,
    email       TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    source      TEXT NOT NULL DEFAULT 'organic',  -- organic | google_ads | referral | walk_in
    campaign_id INTEGER REFERENCES ad_campaigns(id),
    sms_opt_in  BOOLEAN NOT NULL DEFAULT TRUE,
    notes       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS appointments (
    id           SERIAL PRIMARY KEY,
    client_id    INTEGER NOT NULL REFERENCES clients(id),
    staff_id     INTEGER NOT NULL REFERENCES staff(id),
    service_id   INTEGER NOT NULL REFERENCES services(id),
    start_at     TIMESTAMP NOT NULL,
    duration_min INTEGER NOT NULL,
    price        NUMERIC(12,2) NOT NULL,
    status       TEXT NOT NULL DEFAULT 'booked',  -- booked | completed | no_show | cancelled
    created_at   TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_appt_start ON appointments(start_at);
CREATE INDEX IF NOT EXISTS idx_appt_client ON appointments(client_id);

CREATE TABLE IF NOT EXISTS products (
    id            SERIAL PRIMARY KEY,
    sku           TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    unit_cost     NUMERIC(12,2) NOT NULL,
    retail_price  NUMERIC(12,2),                 -- NULL = back-bar supply, not for sale
    on_hand       INTEGER NOT NULL DEFAULT 0,
    reorder_point INTEGER NOT NULL DEFAULT 0,
    reorder_qty   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stock_moves (
    id         SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty_delta  INTEGER NOT NULL,
    reason     TEXT NOT NULL,                    -- purchase | sale | usage | adjustment
    at         TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sales (
    id             SERIAL PRIMARY KEY,
    appointment_id INTEGER UNIQUE REFERENCES appointments(id),
    client_id      INTEGER REFERENCES clients(id),
    staff_id       INTEGER REFERENCES staff(id),
    sold_at        TIMESTAMP NOT NULL DEFAULT now(),
    subtotal       NUMERIC(12,2) NOT NULL,
    tip            NUMERIC(12,2) NOT NULL DEFAULT 0,
    card_fee       NUMERIC(12,2) NOT NULL DEFAULT 0,
    cogs           NUMERIC(12,2) NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL DEFAULT 'card'  -- card | cash
);
CREATE INDEX IF NOT EXISTS idx_sales_at ON sales(sold_at);

CREATE TABLE IF NOT EXISTS sale_items (
    id         SERIAL PRIMARY KEY,
    sale_id    INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,                    -- service | product
    ref_id     INTEGER NOT NULL,
    qty        INTEGER NOT NULL DEFAULT 1,
    unit_price NUMERIC(12,2) NOT NULL,
    unit_cost  NUMERIC(12,2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS expenses (
    id       SERIAL PRIMARY KEY,
    at       DATE NOT NULL,
    category TEXT NOT NULL,                      -- rent | software | supplies | advertising | other
    amount   NUMERIC(12,2) NOT NULL,
    memo     TEXT NOT NULL DEFAULT ''
);

-- ------------------------------------------------------------ growth loop
CREATE TABLE IF NOT EXISTS ad_metrics_daily (
    campaign_id          INTEGER NOT NULL REFERENCES ad_campaigns(id),
    date                 DATE NOT NULL,
    impressions          INTEGER NOT NULL DEFAULT 0,
    clicks               INTEGER NOT NULL DEFAULT 0,
    cost                 NUMERIC(12,2) NOT NULL DEFAULT 0,
    platform_conversions NUMERIC(10,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (campaign_id, date)
);

-- gclid -> campaign map, pulled from Google Ads click_view. Lets us attribute
-- a sign-up to the exact campaign whose ad was clicked.
CREATE TABLE IF NOT EXISTS ad_clicks (
    gclid       TEXT PRIMARY KEY,
    campaign_id INTEGER NOT NULL REFERENCES ad_campaigns(id),
    clicked_on  DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS signups (
    id                   SERIAL PRIMARY KEY,
    at                   TIMESTAMP NOT NULL DEFAULT now(),
    name                 TEXT NOT NULL,
    phone                TEXT,
    email                TEXT,
    gclid                TEXT,
    utm_source           TEXT,
    utm_medium           TEXT,
    utm_campaign         TEXT,
    campaign_id          INTEGER REFERENCES ad_campaigns(id),
    attribution          TEXT NOT NULL DEFAULT 'organic',  -- gclid | utm | organic
    client_id            INTEGER REFERENCES clients(id),
    first_appointment_id INTEGER REFERENCES appointments(id),
    conversion_uploaded  BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_signups_at ON signups(at);

CREATE TABLE IF NOT EXISTS loop_runs (
    id      SERIAL PRIMARY KEY,
    as_of   DATE NOT NULL,
    ran_at  TIMESTAMP NOT NULL DEFAULT now(),
    dry_run BOOLEAN NOT NULL DEFAULT FALSE,
    sense   JSONB NOT NULL DEFAULT '{}',
    think   JSONB NOT NULL DEFAULT '{}',
    act     JSONB NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS forecasts (
    run_id            INTEGER NOT NULL REFERENCES loop_runs(id) ON DELETE CASCADE,
    date              DATE NOT NULL,
    expected_bookings NUMERIC(8,2) NOT NULL,
    already_booked    INTEGER NOT NULL,
    capacity_slots    NUMERIC(8,2) NOT NULL,
    gap_slots         NUMERIC(8,2) NOT NULL,
    PRIMARY KEY (run_id, date)
);
