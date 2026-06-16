-- Yfine canonical schema (generated from SQLModel create_all; head b3c4d5e6f7a8).
-- DO NOT EDIT BY HAND — regenerate via scripts/gen_schema.py.
-- Reproduces the current model schema so a fresh db is compatible; an
-- existing db is never recreated. Drift-tolerant auto-heal (src/db/migrate.ts)
-- adds any tables/columns an OLDER db is missing using expected-schema.json.

PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
	id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	currency VARCHAR NOT NULL, 
	starting_balance FLOAT NOT NULL, 
	exclude_from_stats BOOLEAN NOT NULL, 
	is_savings_fund BOOLEAN NOT NULL, 
	hidden_from_sources BOOLEAN NOT NULL, 
	yield_rate FLOAT NOT NULL, 
	yield_period_months INTEGER NOT NULL, 
	yield_next_date DATE, 
	yield_last_date DATE, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS tags (
	id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	color VARCHAR, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS movements (
	id INTEGER NOT NULL, 
	source_id INTEGER, 
	amount FLOAT NOT NULL, 
	direction VARCHAR NOT NULL, 
	date DATE NOT NULL, 
	note VARCHAR, 
	transfer_pair_id INTEGER, 
	exclude_from_stats BOOLEAN NOT NULL, 
	is_savings_contribution BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id), 
	FOREIGN KEY(transfer_pair_id) REFERENCES movements (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS movement_tag (
	movement_id INTEGER NOT NULL, 
	tag_id INTEGER NOT NULL, 
	PRIMARY KEY (movement_id, tag_id), 
	FOREIGN KEY(movement_id) REFERENCES movements (id) ON DELETE CASCADE, 
	FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS movement_attachments (
	id INTEGER NOT NULL, 
	movement_id INTEGER NOT NULL, 
	filename VARCHAR NOT NULL, 
	stored_name VARCHAR NOT NULL, 
	mime_type VARCHAR NOT NULL, 
	size_bytes INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(movement_id) REFERENCES movements (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recurring_items (
	id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	amount FLOAT NOT NULL, 
	direction VARCHAR NOT NULL, 
	currency VARCHAR NOT NULL, 
	frequency VARCHAR NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE, 
	source_id INTEGER, 
	apply_mode VARCHAR NOT NULL, 
	next_due_date DATE NOT NULL, 
	alert_days_before INTEGER NOT NULL, 
	alert_if_insufficient BOOLEAN NOT NULL, 
	last_fired_date DATE, 
	last_alert_date DATE, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id)
);

CREATE TABLE IF NOT EXISTS notifications (
	id INTEGER NOT NULL, 
	type VARCHAR NOT NULL, 
	title VARCHAR NOT NULL, 
	body VARCHAR NOT NULL, 
	related_entity VARCHAR, 
	is_read BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS settings (
	id INTEGER NOT NULL, 
	locale VARCHAR NOT NULL, 
	date_format VARCHAR NOT NULL, 
	base_currency VARCHAR, 
	theme VARCHAR NOT NULL, 
	hide_net_worth BOOLEAN NOT NULL, 
	last_source_id INTEGER, 
	mobile_nav_mode VARCHAR NOT NULL, 
	ui_scale VARCHAR NOT NULL, 
	hotkeys_enabled BOOLEAN NOT NULL, 
	hotkeys_json VARCHAR NOT NULL, 
	nav_layout_json VARCHAR NOT NULL, 
	lan_access BOOLEAN NOT NULL, 
	portfolio_prices_enabled BOOLEAN NOT NULL, 
	portfolio_prices_prompted BOOLEAN NOT NULL, 
	saved_views_json VARCHAR NOT NULL, 
	movement_templates_json VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS whims (
	id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	amount FLOAT NOT NULL, 
	currency VARCHAR NOT NULL, 
	priority VARCHAR NOT NULL, 
	source_id INTEGER, 
	status VARCHAR NOT NULL, 
	note VARCHAR, 
	url VARCHAR, 
	purchased_at DATETIME, 
	linked_goal_id INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id)
);

CREATE TABLE IF NOT EXISTS savings (
	id INTEGER NOT NULL, 
	amount FLOAT NOT NULL, 
	currency VARCHAR NOT NULL, 
	date DATE NOT NULL, 
	description VARCHAR, 
	note VARCHAR, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS saving_tag (
	saving_id INTEGER NOT NULL, 
	tag_id INTEGER NOT NULL, 
	PRIMARY KEY (saving_id, tag_id), 
	FOREIGN KEY(saving_id) REFERENCES savings (id) ON DELETE CASCADE, 
	FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exchange_rates (
	id INTEGER NOT NULL, 
	from_currency VARCHAR NOT NULL, 
	to_currency VARCHAR NOT NULL, 
	rate FLOAT NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS portfolios (
	id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	kind VARCHAR NOT NULL, 
	base_currency VARCHAR NOT NULL, 
	source_id INTEGER NOT NULL, 
	note VARCHAR, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS holdings (
	id INTEGER NOT NULL, 
	portfolio_id INTEGER NOT NULL, 
	asset_class VARCHAR NOT NULL, 
	symbol VARCHAR NOT NULL, 
	display_name VARCHAR, 
	quantity FLOAT NOT NULL, 
	avg_cost FLOAT NOT NULL, 
	currency VARCHAR NOT NULL, 
	last_price FLOAT, 
	last_price_at DATETIME, 
	manual_price BOOLEAN NOT NULL, 
	note VARCHAR, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(portfolio_id) REFERENCES portfolios (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS holding_price_snapshots (
	id INTEGER NOT NULL, 
	holding_id INTEGER NOT NULL, 
	date DATE NOT NULL, 
	price FLOAT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_holding_snapshot_date UNIQUE (holding_id, date), 
	FOREIGN KEY(holding_id) REFERENCES holdings (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS goals (
	id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	target_amount FLOAT NOT NULL, 
	currency VARCHAR NOT NULL, 
	target_date DATE, 
	source_id INTEGER NOT NULL, 
	status VARCHAR NOT NULL, 
	note VARCHAR, 
	linked_whim_id INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id) ON DELETE RESTRICT, 
	FOREIGN KEY(linked_whim_id) REFERENCES whims (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS goal_allocations (
	id INTEGER NOT NULL, 
	goal_id INTEGER NOT NULL, 
	movement_id INTEGER NOT NULL, 
	amount FLOAT NOT NULL, 
	date DATE NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(goal_id) REFERENCES goals (id) ON DELETE CASCADE, 
	FOREIGN KEY(movement_id) REFERENCES movements (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS budgets (
	id INTEGER NOT NULL, 
	tag_id INTEGER NOT NULL, 
	amount FLOAT NOT NULL, 
	currency VARCHAR NOT NULL, 
	period VARCHAR NOT NULL, 
	direction VARCHAR NOT NULL, 
	rollover BOOLEAN NOT NULL, 
	alert_threshold_pct INTEGER NOT NULL, 
	active BOOLEAN NOT NULL, 
	start_date DATE NOT NULL, 
	last_alert_period VARCHAR, 
	last_alert_level INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tag_id) REFERENCES tags (id)
);

-- indexes
CREATE INDEX IF NOT EXISTS ix_budgets_tag_id ON budgets (tag_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_exchange_rates_pair ON exchange_rates (from_currency, to_currency);
CREATE INDEX IF NOT EXISTS ix_goal_allocations_goal_id ON goal_allocations (goal_id);
CREATE INDEX IF NOT EXISTS ix_goal_allocations_movement_id ON goal_allocations (movement_id);
CREATE INDEX IF NOT EXISTS ix_goals_source_id ON goals (source_id);
CREATE INDEX IF NOT EXISTS ix_goals_status ON goals (status);
CREATE INDEX IF NOT EXISTS ix_holding_price_snapshots_holding_date ON holding_price_snapshots (holding_id, date);
CREATE INDEX IF NOT EXISTS ix_holdings_portfolio_id ON holdings (portfolio_id);
CREATE INDEX IF NOT EXISTS ix_movement_attachments_movement_id ON movement_attachments (movement_id);
CREATE INDEX IF NOT EXISTS ix_movements_date ON movements (date);
CREATE INDEX IF NOT EXISTS ix_movements_source_id ON movements (source_id);
CREATE INDEX IF NOT EXISTS ix_movements_source_id_direction ON movements (source_id, direction);
CREATE INDEX IF NOT EXISTS ix_movements_transfer_pair_id ON movements (transfer_pair_id);
CREATE INDEX IF NOT EXISTS ix_notifications_created_at ON notifications (created_at);
CREATE INDEX IF NOT EXISTS ix_notifications_is_read ON notifications (is_read);
CREATE INDEX IF NOT EXISTS ix_notifications_related_entity_type ON notifications (related_entity, type);
CREATE INDEX IF NOT EXISTS ix_recurring_items_next_due_date ON recurring_items (next_due_date);
CREATE INDEX IF NOT EXISTS ix_recurring_items_source_id ON recurring_items (source_id);

-- alembic_version: schema revision marker (round-trip compatible
-- with the legacy Python app). Never overwrites an existing stamp.
CREATE TABLE IF NOT EXISTS alembic_version (
	version_num VARCHAR(32) NOT NULL,
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO alembic_version (version_num)
SELECT 'b3c4d5e6f7a8'
WHERE NOT EXISTS (SELECT 1 FROM alembic_version);
