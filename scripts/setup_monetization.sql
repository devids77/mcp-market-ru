-- API Keys table for paid access
CREATE TABLE IF NOT EXISTS api_keys (
    id SERIAL PRIMARY KEY,
    key VARCHAR(64) UNIQUE NOT NULL,
    owner_name VARCHAR(255) NOT NULL,
    owner_email VARCHAR(255) NOT NULL,
    plan VARCHAR(50) DEFAULT 'free',  -- free, starter, pro, enterprise
    requests_limit INTEGER DEFAULT 100,  -- per day
    requests_used INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    last_used_at TIMESTAMP WITH TIME ZONE
);

-- Usage logs for analytics and billing
CREATE TABLE IF NOT EXISTS usage_logs (
    id SERIAL PRIMARY KEY,
    api_key_id INTEGER REFERENCES api_keys(id),
    tool_name VARCHAR(100) NOT NULL,
    params JSONB,
    response_size INTEGER,
    execution_ms INTEGER,
    ip_address VARCHAR(45),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Leads from request_quote - this is money
CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id),
    company_slug VARCHAR(255),
    client_name VARCHAR(255),
    client_phone VARCHAR(50),
    client_email VARCHAR(255),
    project_description TEXT,
    budget_from INTEGER,
    budget_to INTEGER,
    region VARCHAR(255),
    category VARCHAR(255),
    status VARCHAR(50) DEFAULT 'new',  -- new, contacted, qualified, converted, lost
    source VARCHAR(100) DEFAULT 'mcp_api',
    api_key_id INTEGER REFERENCES api_keys(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Premium company listings
CREATE TABLE IF NOT EXISTS premium_listings (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id),
    plan VARCHAR(50) DEFAULT 'basic',  -- basic, featured, premium
    priority_rank INTEGER DEFAULT 0,
    badge_text VARCHAR(100),
    highlight_color VARCHAR(20),
    is_active BOOLEAN DEFAULT true,
    starts_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    monthly_price INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_api_keys_key ON api_keys(key);
CREATE INDEX IF NOT EXISTS idx_usage_logs_key ON usage_logs(api_key_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created ON usage_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_company ON leads(company_id);
CREATE INDEX IF NOT EXISTS idx_premium_active ON premium_listings(is_active, company_id);

-- Insert demo API key for testing
INSERT INTO api_keys (key, owner_name, owner_email, plan, requests_limit)
VALUES 
    ('mcp_free_demo_2026', 'Demo User', 'demo@mcp-market.ru', 'free', 100),
    ('mcp_test_pro_key01', 'Test Pro', 'pro@mcp-market.ru', 'pro', 5000)
ON CONFLICT (key) DO NOTHING;

-- Add is_premium column to companies if not exists
DO $$ BEGIN
    ALTER TABLE companies ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT false;
    ALTER TABLE companies ADD COLUMN IF NOT EXISTS premium_rank INTEGER DEFAULT 0;
EXCEPTION WHEN OTHERS THEN NULL;
END $$;

SELECT 'Monetization tables created successfully!' as result;
