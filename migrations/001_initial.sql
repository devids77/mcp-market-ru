-- MCP Market - Initial Schema
-- Run automatically on first PostgreSQL start

-- Companies table
CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE,
    
    -- Classification
    category VARCHAR(100),
    subcategories TEXT[] DEFAULT '{}',
    
    -- Location
    region VARCHAR(100),
    city VARCHAR(100),
    address TEXT,
    
    -- Details
    description TEXT,
    website VARCHAR(500),
    phone VARCHAR(50),
    email VARCHAR(255),
    
    -- Pricing
    price_per_sqm_min INTEGER,
    price_per_sqm_max INTEGER,
    min_project_price INTEGER,
    max_project_price INTEGER,
    
    -- Reputation
    rating DECIMAL(2,1),
    reviews_count INTEGER DEFAULT 0,
    projects_count INTEGER DEFAULT 0,
    
    -- Source tracking
    source VARCHAR(50),
    source_url TEXT,
    source_id VARCHAR(255),
    
    -- Status: auto (parsed), claimed (owner confirmed), verified, premium
    status VARCHAR(20) DEFAULT 'auto',
    
    -- If company has its own MCP server
    own_mcp_url VARCHAR(500),
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    claimed_at TIMESTAMP WITH TIME ZONE
);

-- Projects (houses, buildings, etc.)
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255),
    slug VARCHAR(255),
    
    -- Characteristics
    area DECIMAL(8,2),
    floors INTEGER,
    bedrooms INTEGER,
    bathrooms INTEGER,
    material VARCHAR(50),
    style VARCHAR(50),
    dimensions VARCHAR(50),
    
    -- Pricing
    price INTEGER,
    price_per_sqm INTEGER,
    price_description VARCHAR(255),
    
    -- Content
    description TEXT,
    features TEXT[] DEFAULT '{}',
    images TEXT[] DEFAULT '{}',
    url VARCHAR(500),
    
    -- Source
    source VARCHAR(50),
    source_url TEXT,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Agent queries (analytics)
CREATE TABLE IF NOT EXISTS agent_queries (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    tool_name VARCHAR(50) NOT NULL,
    params JSONB DEFAULT '{}',
    results_count INTEGER DEFAULT 0,
    duration_ms INTEGER,
    client_info VARCHAR(255),
    ip_address INET
);

-- Leads
CREATE TABLE IF NOT EXISTS leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    project_id UUID REFERENCES projects(id),
    
    -- Contact
    name VARCHAR(255),
    phone VARCHAR(50),
    email VARCHAR(255),
    comment TEXT,
    
    -- Meta
    source VARCHAR(50) DEFAULT 'mcp',
    agent_query_id BIGINT,
    status VARCHAR(20) DEFAULT 'new',
    
    -- CRM
    crm_lead_id VARCHAR(100),
    sent_to_crm_at TIMESTAMP WITH TIME ZONE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Users (company owners who claimed their cards)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(50),
    company_id UUID REFERENCES companies(id),
    role VARCHAR(20) DEFAULT 'owner',
    tariff VARCHAR(20) DEFAULT 'free',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_companies_category ON companies(category);
CREATE INDEX IF NOT EXISTS idx_companies_region ON companies(region);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_companies_slug ON companies(slug);

CREATE INDEX IF NOT EXISTS idx_projects_company ON projects(company_id);
CREATE INDEX IF NOT EXISTS idx_projects_area ON projects(area);
CREATE INDEX IF NOT EXISTS idx_projects_material ON projects(material);
CREATE INDEX IF NOT EXISTS idx_projects_price ON projects(price);
CREATE INDEX IF NOT EXISTS idx_projects_floors ON projects(floors);

CREATE INDEX IF NOT EXISTS idx_queries_timestamp ON agent_queries(timestamp);
CREATE INDEX IF NOT EXISTS idx_queries_tool ON agent_queries(tool_name);

CREATE INDEX IF NOT EXISTS idx_leads_company ON leads(company_id);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at);

-- Full-text search indexes (Russian language)
CREATE INDEX IF NOT EXISTS idx_companies_fts ON companies 
    USING GIN(to_tsvector('russian', COALESCE(name, '') || ' ' || COALESCE(description, '') || ' ' || COALESCE(city, '')));

CREATE INDEX IF NOT EXISTS idx_projects_fts ON projects 
    USING GIN(to_tsvector('russian', COALESCE(name, '') || ' ' || COALESCE(description, '')));

-- Insert ScandiEcoDom as the first company
INSERT INTO companies (name, slug, category, subcategories, region, city, description, website, phone, price_per_sqm_min, price_per_sqm_max, min_project_price, source, status, own_mcp_url)
VALUES (
    'СкандиЭкоДом',
    'scandiecodom',
    'каркасные_дома',
    ARRAY['каркасные', 'скандинавские', 'экодома'],
    'Московская область',
    'Москва',
    'Строительство каркасных домов в скандинавском стиле. Более 140 проектов домов от 40 до 250 м². Собственное производство, работаем по всей России.',
    'https://scandiecodom.ru',
    NULL,
    25000,
    80000,
    2000000,
    'manual',
    'verified',
    'https://mcp.scandiecodom.ru'
) ON CONFLICT (slug) DO NOTHING;
