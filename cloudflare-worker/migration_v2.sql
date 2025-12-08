-- Migration: scan_location (single) -> scan_locations (JSON array)
-- Run with: wrangler d1 execute sc-hauling-db --file=migration_v2.sql

-- Add the new column
ALTER TABLE scans ADD COLUMN scan_locations TEXT;

-- Migrate existing data: convert single location to JSON array
UPDATE scans
SET scan_locations = CASE
    WHEN scan_location IS NOT NULL THEN json_array(scan_location)
    ELSE '[]'
END;

-- Note: SQLite doesn't support dropping columns directly in older versions.
-- The old scan_location column will remain but won't be used.
-- For a clean schema, you would need to recreate the table.
