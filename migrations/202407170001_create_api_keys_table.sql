-- Migration: create API keys table for hardened API
CREATE TABLE IF NOT EXISTS api_keys (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    key_hash CHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    last_used_at TIMESTAMP WITH TIME ZONE,
    rate_limit_override INTEGER,
    scopes TEXT[] DEFAULT ARRAY[]::TEXT[],
    CONSTRAINT api_keys_name_chk CHECK (char_length(name) >= 3)
);

CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys (key_hash);
