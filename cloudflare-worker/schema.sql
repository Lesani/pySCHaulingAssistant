-- SC Hauling Assistant - Mission Scans Database Schema
-- Run with: wrangler d1 execute sc-hauling-db --file=schema.sql

CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    scan_timestamp TEXT NOT NULL,
    scan_location TEXT,
    reward REAL DEFAULT 0,
    availability TEXT,
    rank TEXT,
    contracted_by TEXT,
    objectives TEXT,  -- JSON array
    uploaded_by TEXT DEFAULT 'anonymous',
    uploaded_at TEXT NOT NULL
);

-- Index for efficient sync queries
CREATE INDEX IF NOT EXISTS idx_scans_uploaded_at ON scans(uploaded_at);

-- Index for location filtering
CREATE INDEX IF NOT EXISTS idx_scans_location ON scans(scan_location);

-- Index for reward sorting
CREATE INDEX IF NOT EXISTS idx_scans_reward ON scans(reward DESC);

-- Discord users table
CREATE TABLE IF NOT EXISTS users (
    discord_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    avatar TEXT,
    created_at TEXT NOT NULL,
    last_login TEXT NOT NULL
);

-- Session tokens table (for app authentication)
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    discord_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (discord_id) REFERENCES users(discord_id)
);

-- Index for session cleanup and lookup
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_discord_id ON sessions(discord_id);
