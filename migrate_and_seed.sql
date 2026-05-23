-- Task management tables for MCP Market dashboard
-- Migration script

CREATE TABLE IF NOT EXISTS task_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT DEFAULT '#3B82F6',
    icon TEXT DEFAULT 'P',
    sort_order INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS task_items (
    id SERIAL PRIMARY KEY,
    project_id TEXT REFERENCES task_projects(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    status TEXT DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'done')),
    date TEXT,
    sort_order INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_items_project ON task_items(project_id);
CREATE INDEX IF NOT EXISTS idx_task_items_status ON task_items(status);

-- Seed projects
INSERT INTO task_projects (id, name, color, icon, sort_order) VALUES
('mm', 'MCP Market Russia', '#3B82F6', 'M', 0),
('mcp-scandi', 'MCP СкандиЭкоДом', '#10B981', 'С', 1),
('openclaw-nexa', 'OpenClaw → Nexa', '#8B5CF6', 'N', 2),
('openclaw-scandi', 'OpenClaw → Сканди', '#F59E0B', 'С', 3),
('openclaw-alexey', 'OpenClaw → Алексей', '#EF4444', 'А', 4),
('openclaw-calc', 'OpenClaw → Calculator', '#06B6D4', 'К', 5),
('polymarket', 'Polymarket', '#6366F1', 'P', 6),
('cowork', 'Cowork / Claude', '#EC4899', 'C', 7),
('automation', 'Автоматизация', '#14B8A6', 'A', 8),
('scandi-auto', 'СкандиАвтоматизация PRO', '#D946EF', 'S', 9),
('calc-v2', 'Калькулятор V2', '#F97316', 'V', 10)
ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, color=EXCLUDED.color, icon=EXCLUDED.icon, sort_order=EXCLUDED.sort_order;

-- Seed tasks: MCP Market Russia (mm)
INSERT INTO task_items (project_id, text, status, date, sort_order) VALUES
('mm', 'Удалены 1325 фейковых проектов', 'done', '2026-03-20', 0),
('mm', 'Обновлён main.py до v2.1.0: 9 tools', 'done', '2026-03-20', 1),
('mm', 'Обогащение слагами — 1477 компаний', 'done', '2026-03-20', 2),
('mm', 'Multistep Score: Z1 = 30', 'done', '2026-03-20', 3),
('mm', 'Импорт 140 реальных проектов', 'done', '2026-03-21', 4),
('mm', 'Калькулятор стоимости — 10-й tool, v2.2.0', 'done', '2026-03-21', 5),
('mm', 'Обогащение: 1305 телефонов, 710 email, 1630 описаний', 'done', '2026-03-21', 6),
('mm', 'Дашборд v3 + Data Completeness + Recent Queries', 'done', '2026-03-23', 7),
('mm', 'Парсинг рейтингов Google Places — 280+ компаний', 'done', '2026-03-23', 8),
('mm', 'Полное обогащение рейтингов всех 1305 компаний', 'in_progress', NULL, 9),
('mm', 'Парсинг рейтингов Яндекс Карт', 'todo', NULL, 10),
('mm', 'Регистрация в каталогах: Glama.ai, mcpdb.ru', 'todo', NULL, 11),
('mm', 'Карта России с точками компаний', 'todo', NULL, 12),
('mm', 'Автообновляемые стоп', 'todo', NULL, 13);

-- Seed tasks: MCP СкандиЭкоДом (mcp-scandi)
INSERT INTO task_items (project_id, text, status, date, sort_order) VALUES
('mcp-scandi', 'Прагматик — реальные URL проектов', 'done', '2026-03-21', 0),
('mcp-scandi', '140 проектов с реальными ссылками', 'done', '2026-03-21', 1),
('mcp-scandi', 'Синхронизация новых проектов', 'todo', NULL, 2);

-- Seed tasks: OpenClaw → Nexa (openclaw-nexa)
INSERT INTO task_items (project_id, text, status, date, sort_order) VALUES
('openclaw-nexa', '11 скиллов документированы', 'done', '2026-03-23', 0),
('openclaw-nexa', 'Обновление базы знаний', 'todo', NULL, 1),
('openclaw-nexa', 'Маркетинговые тексты', 'todo', NULL, 2);

-- Seed tasks: OpenClaw → Сканди (openclaw-scandi)
INSERT INTO task_items (project_id, text, status, date, sort_order) VALUES
('openclaw-scandi', 'Скрипт расчёта домов в открытых линиях', 'in_progress', NULL, 0),
('openclaw-scandi', 'Научить корректно считать стоимость', 'todo', NULL, 1),
('openclaw-scandi', 'Тестирование сценариев общения', 'todo', NULL, 2);

-- Other projects continue...
