# MCP Market Russia — Status

## Обновлено: 2026-04-16

### Инфраструктура
- Сервер: 212.193.27.12
- Docker: 2 контейнера (mcp-server + mcp-db) — UP
- PostgreSQL 16, FastMCP, workers=1
- Bind mount: ./app:/app/app (правки на хосте live)
- SSL: Let's Encrypt, nginx reverse proxy

### Данные
- Компаний: 3 395 (18 регионов)
- Проектов: 13 436
- MCP-инструментов: 21
- Полнота: описание 52%, рейтинг 96%, сайт 62%, телефон 44%, email 60%

### Страницы (единая навигация)
- `/` — Главная landing
- `/dashboard` — Дашборд (статистика, графики, топы)
- `/pricing` — Тарифы (Starter/Pro/Enterprise + CTA крипто)
- `/pay` — Оплата криптой (3-step wizard: BTC/ETH/USDT)
- `/admin` — Админ-панель (ключи, платежи, использование, лиды)
- `/mcp/` — MCP landing (content-negotiation)

### API Endpoints
- `/api/keys` — список API ключей
- `/api/register` — регистрация ключа
- `/api/keys/{key_id}/toggle` — вкл/выкл ключ
- `/api/payments/create` — создать платёж (крипто)
- `/api/payments/{id}` — статус платежа
- `/api/payments/{id}/confirm` — подтвердить платёж (создаёт ключ)
- `/api/payments` — список всех платежей
- `/api/leads` — лиды
- `/api/usage/stats` — статистика использования
- `/api/pricing` — тарифы JSON
- `/api/dashboard/*` — 8 endpoints для дашборда

### Платёжная система (крипто)
- Валюты: BTC, ETH, USDT TRC-20
- Тарифы: Starter 2990р, Pro 9990р, Enterprise 24990р
- Flow: выбор плана → данные+валюта → payment_id+кошелёк+таймер
- Админ подтверждает → авто-создание API ключа
- Кошельки: PLACEHOLDER (нужны реальные)
- Таблица payments: 15 колонок, CHECK constraint, auto-expire 24h

### Админ-панель
- Пароль: McpAdmin2026!
- 4 вкладки: API Ключи, Использование, Платежи, Лиды
- Toast-уведомления (не блокирующие)
- Подтверждение платежей с TX hash → авто-создание ключа

### Тестовый flow (проверено 2026-04-16)
- Dashboard → Pay → Create payment (USDT Pro) → Admin confirm → API key created ✓
- 9 API ключей, 2 платежа (1 completed, 1 pending)

### TODO
- [ ] Заменить placeholder крипто-кошельки на реальные
- [ ] Email-уведомления при подтверждении оплаты
- [ ] Enrichment телефонов (2GIS/Playwright)
- [ ] SEO / маркетинг

## 2026-04-20 — GitHub PR #4940 cleanup
- Fork devids77/awesome-mcp-servers: ранее сломанный коммит оставил строку propstack-mcp обрезанной и смешанной с MCP Market Russia. Сегодня вторым коммитом (661b6f8 + новый) полностью восстановлена upstream-строка propstack и добавлена чистая одиночная строка для devids77/mcp-market-ru с GitHub URL под **Real Estate**.
- Правка сделана через CM6 EditorView, доступ к которому найден через `document.querySelector('.cm-content').cmTile.view` — позволяет dispatch transaction напрямую, минуя проблему виртуализированной прокрутки (у больших README > 600KB).
- Новый репо: https://github.com/devids77/mcp-market-ru (README 5.6KB, MIT LICENSE).
- PR #4940: заголовок переписан без emoji → `Add mcp-market-ru: Russian construction market data server`; body переработан, ссылается на GitHub репо, даёт Repository/Live endpoint/Demo/Protocol/License.
- Старые bot-метки (has-emoji, non-github-url, duplicate, missing-glama) на PR остаются стейл — бот применил их 4 дня назад. Title + URL уже исправлены; maintainer должен переоценить.
- **Блокер:** Glama badge. Anthropic-агенту нельзя регистрироваться на сторонних сервисах → нужна ручная регистрация пользователя на glama.ai, индексация репо devids77/mcp-market-ru, добавление badge-URL в README (оба — в нашем репо и в строке awesome-mcp-servers).

## 2026-04-20 — New MCP tools (21 → 24)

### Done
- ✅ Designed 3 new tools after audit of existing 21
- ✅ Implemented and deployed to /opt/mcp-market/app/main.py (+233 lines)
- ✅ Container restarted, FastMCP reports 24 registered tools
- ✅ Live-tested all 3 against prod DB

### New tools

1. **`export_search_csv(entity, query, category, region, budget_max, limit)`** — exports search results as CSV with UTF-8 BOM (Excel-friendly). Works for `companies` and `projects`. Returns CSV text up to 2000 rows.

2. **`smart_match(brief, top_n)`** — natural-language Russian brief → top-N contractors. Parses region, category, area_sqm, budget (с "млн" суффиксом), quality class. Returns JSON with parsed filters + matches + explanation.

3. **`get_lead_status(lead_id, api_key)`** — tracks lead lifecycle after request_quote. Validates api_key, joins leads+companies, returns status (new/contacted/won/lost), timestamps, CRM lead_id.

### Verification

- `docker exec mcp-server python -c "from app.main import mcp; ..."` → 24 tools listed
- smart_match('каркасный дом 180 кв.м в Подмосковье до 15 млн') → correctly parsed region=Московская область, category=Каркасные дома, area=180, budget=15_000_000
- smart_match('дом в Подмосковье') → top match: РЕК Интеграл, Московская область
- export_search_csv('companies', region='Москва', limit=3) → 761 bytes valid CSV
- get_lead_status(fake_id, 'bogus_key') → `{"error": "Invalid or inactive api_key"}`

### README on GitHub
- 2026-04-20: README.md в devids77/mcp-market-ru обновлён (21 → 24 tools), добавлены строки для export_search_csv / smart_match / get_lead_status. Commit directly to main через CM6 EditorView.dispatch.

## 2026-04-20 — Live snapshot (post-deploy)
- Containers: mcp-server Up 3h (after 24-tool restart), mcp-db Up 13d healthy
- API keys: 9 total = 6 free + 2 pro + 1 starter — все тестовые, реальных пользователей нет
- Active usage: pro@mcp-market.ru used=12 (last 2026-04-06), starter@test.com used=2, остальные 0-1
- Leads: 1 total, status=new, никакого движения 7+ дней
- Вывод: нужен онбординг — anonymous-доступ к ключевым тулам через FREE_TOOLS, чтобы AI-агенты могли пробовать без регистрации


### 2026-04-20 — smart_match → FREE_TOOLS + category_map fix
- FREE_TOOLS расширен с 10 до **11** инструментов (добавлен `smart_match`).
- Bug-fix: `category_map` в smart_match возвращал title-case названия ("Каркасные дома"), а в DB категории slug-style ("каркасные_дома"). Исправлены все 15 маппингов: каркас→каркасные_дома, брусов→дома_из_бруса, кирпич→кирпич, остальные (газобетон, сип, бревен, сруб, бан, гараж, коттедж, таунхаус, пеноблок, керамзит, блочн)→строительство (единственная generic-категория в DB).
- Тест: `smart_match("каркасный дом 180 кв.м в Подмосковье до 15 млн", 3)` → matches: 3, первый = "Летний сезон, проектно-строительная компания" (было 0 до фикса).
- Backup: /opt/mcp-market/app/main.py.bak-20260420-freetools, .bak-20260420-catmap.

### 2026-04-20 — smart_match parser recall (склонения + строительство)
- region_map: добавлены "уф"→Башкортостан (для склонений Уфа/Уфе/Уфы) и "московск"→Московская область (исправление typo "мосовск"→"московск", original key оставлен для backwards-compat).
- category_map: добавлены "строительств"→строительство, "постройк"→строительство, "дом под ключ"→строительство. Критично: "строительство" — крупнейшая категория в DB (2616 из 3395), без этого маппинга брифы "строительство в N" не находили категорию.
- Smoke-test 5 брифов: было 2 брифа с parser-ошибками, стало 0. Data-limit остался для "кирпич" (20 шт) и "дома_из_бруса" (1 шт) — это не баг parser.
- Backup: /opt/mcp-market/app/main.py.bak-20260420-recall

### 2026-04-20 — Glama badge + awesome-mcp-servers PR #4940
- README на GitHub: добавлен Glama badge (4-й badge, строка 6). Commit 986b18b: "Add Glama MCP Server badge to README".
- awesome-mcp-servers PR #4940: обновлена строка 1774 в fork (devids77/awesome-mcp-servers), добавлен Glama score-badge + 21→24 tools. Commit 42daff3: "Add Glama badge + update mcp-market-ru to 24 tools".
- PR labels: github-actions bot автоматически убрал `missing-glama`, добавил `has-glama`. All checks passed. No merge conflicts.
- Блокер на merge: Glama security+quality score evaluation (сейчас license=A, security/quality=not tested) — это их авто-процесс.
- URL badges: PNG preview 760×400 = /servers/devids77/mcp-market-ru/badge; SVG score-shield = /servers/devids77/mcp-market-ru/badges/score.svg.

### 2026-04-20 — /demo: smart_match live showcase
- Добавлен REST-wrapper `/api/v1/smart-match?brief=...&top_n=3` в main.py (конец файла). Anonymous access через FREE tier-map (строка 135 добавлена `"/api/v1/smart-match": "free"`).
- demo.html: перед `</body>` встроен блок `#smart-match-demo` — textarea + button + live-рендер parsed (region/category/area/budget/quality) и top-3 matches с рейтингом/отзывами.
- Вёрстка inline-CSS под тёмную тему (#1a1f2e/#2d3e6b/#e8ecf0), JS fetch без зависимостей, ~4.8KB.
- E2E-тест в Chrome: "каркасный дом 180 кв.м в Подмосковье до 15 млн" → HTTP 200, parsed ✓, 3 подрядчика рендерятся (Летний сезон 4.7★, Тентпро 4.6★, Фабрика торг. оборудования 4.5★).
- Backups: main.py.bak-20260420-restwrapper, demo.html.bak-20260420-smartmatch.

### 2026-04-24 — GitHub + Glama hygiene (без изменений на сервере)
- PR #4940 description: переписан — "21 tools" → "24 tools", добавлено упоминание smart_match, убрана stale реплика про earlier commit.
- GitHub repo ABOUT: описание обновлено на 24 tools + smart_match, добавлен homepage https://mcp-market.ru/, 9 topics (mcp, model-context-protocol, ai-agents, claude, russian-market, construction-market, lead-generation, fastmcp, streamable-http).
- glama.json добавлен в корень репо (commit 4f478fa, минимальный maintainer claim devids77).
- GitHub release v0.1.0 "Initial public release" создан.
- Glama Admin: описание обновлено (24 tools + smart_match), Sync Server нажата вручную (last commit 4f478fa распознан).
- Sanity-check 2026-04-24: все 6 чеков зелёные (syntax, tier-map, FREE_TOOLS, demo.html, containers, REST anonymous).

### 2026-04-24 — search_companies recall fix (падежи + многополевой поиск)
- Bug: `/api/v1/search/companies?q=...` искал фразу целиком только в name+description → 0 результатов для "Заборы в Краснодаре", "Фасадные работы москва" и т.д.
- Fix: split query на слова → stop-words filter (в, на, до, под, от, для, и, с, или, за, у, к, по, из, о, при, без, над, со, об) → suffix strip (слова >4 символов теряют 2 последние буквы для склонений) → каждое слово ищется в 5 полях (name, description, region, city, category) через ILIKE, AND между словами.
- Результат smoke-test 6 chip-запросов: было 3/6 работающих, стало 5/6. "Ремонт квартир спб" остался 0 т.к. "ремонт" не в фокусе DB + "спб" это synonym (нужен smart_match).
- Backup: /opt/mcp-market/app/main.py.bak-20260424-searchfix
- Измения в функции: async def api_v1_search_companies (ветка `if q:`).

### 2026-04-24 — Phase 1: regex classifier + tags[] column (БОЛЬШАЯ РЕФОРМА recall)
- User catch: "каркасные дома в спб" выдавало 1 компанию из 3395 — проблема глубже search, плохая сегментация.
- DB reality check: категорий всего 5 (77% в "строительство"), 48% компаний с пустыми описаниями.
- Fix:
  1. ALTER TABLE companies ADD COLUMN tags text[] + GIN-index.
  2. /opt/mcp-market/app/scripts/tag_classifier.py — regex-классификатор с 30 тегами (каркас/брус/кирпич/газобетон/сип/бревно/коттедж/таунхаус/баня/гараж/бытовка/заборы/кровля/фасад/отделка/ремонт/окна_двери/полы/инженерка/ландшафт/бассейн/снос/монтаж/проектирование/строительство/дом_под_ключ/малоэтажн/многоэтажн/недвижимость).
  3. Прогон: 2093/3395 (62%) компаний классифицированы, 1302 остались без тегов (пустые desc — кандидаты в AI Фазу 2).
  4. search_companies обновлён: matching по tags[] OR 5 text fields.
- Результаты smoke-test: 3/6 запросов → 7/8. "Бани в Краснодаре" 0→4, "Коттедж под ключ" 0→26, "Инженерные сети" 0→7.
- API key Z.AI GLM-5.1 сохранён в /opt/mcp-market/.env как Z_AI_API_KEY для Phase 2.
- Backup: main.py.bak-20260424-searchfix (пре-tags[]), classifier живёт в /app/scripts (mounted).

### 2026-04-24 — Phase 2 AI classifier (Z.AI GLM-4.6) — запущен full run
- Discovery 1: Z.AI GLM Coding Pro план использует ОТДЕЛЬНЫЙ endpoint `https://open.bigmodel.cn/api/coding/paas/v4/chat/completions` (не `/api/paas/v4/...` и не api.z.ai). Обычный endpoint возвращает error 1113 "Insufficient balance" потому что Coding-подписка отдельно от pay-as-you-go.
- Discovery 2: auth — **простой Bearer с полным ключом** `{id}.{secret}` as-is (НЕ JWT).
- Discovery 3: glm-4.6 — thinking-модель, все токены уходят в `reasoning_content` если не передать `"thinking": {"type": "disabled"}`. Без этого параметра content пустой, finish_reason=length.
- Pilot 50: 100% API success (ok=50/50), 14% tag-coverage (7/50 получили теги). 4 мин, качество высокое.
- Full run 1295 запущен в background через `docker exec -d` + `/tmp/phase2_full.log`. ETA 60-90 min.
- Скрипт: /opt/mcp-market/app/scripts/tag_classifier_ai.py (85 lines).
- Memory: project_mcp_market_tags_classifier.md обновлён с endpoint/auth/thinking деталями.

### 2026-04-24 — Phase 2 COMPLETED
- Full run: 1295 companies, ok=1293, fail=2 (1 timeout + 1 китайский content filter), elapsed 36.8 min.
- Coverage: 2304/3395 = **68%** (был 62% после Phase 1).
- 1091 без тегов = generic названия где AI не выдумал теги (правильно).
- Smoke-test: "Агентство недвижимости в Москве" → 67, "Коттедж под ключ" → 28, "Инженерные сети" → 7, "Бассейн в Краснодаре" → 2.
- TaskList #30 closed.

### 2026-04-24 — search_companies synonym-expansion (финал)
- User: "Каркасные дома в спб = 1 компания, фигня". Bug: stem "спб" не matchится с "Санкт-Петербург"/"Ленинградская обл.", а stem-strip "Подмосковье"→"Подмосков" тоже не matched (DB region="Московская область").
- Fix: добавлен dict _SYN с 14 shorthand-mappings: спб/питер/петер/пите → санкт-петер|ленинград|петербург, мск → москв, екб/нск/крд/нн/уфа/уф/казан/сочи + подмосков/подмоск → московск|москв.
- Логика: для каждого stem строим OR-цепочку из (alts = [stem] + _SYN.get(stem, [])), каждая alt проверяется в tags[] OR 5 text fields.
- Результаты: "Каркасные дома в спб" 1→6, "Дом из бруса в спб" 0→2, "Ремонт квартир спб" 0→4, "Заборы в питере" 0→6, "Каркасный дом в Подмосковье" 0→12, "Бани в спб" 0→2.
- Backups: main.py.bak-20260424-* (несколько с разных этапов).

### 2026-04-25 — Forward-fix tag classifier in full_parser.py
- `/opt/mcp-market/scripts/full_parser.py`: добавлен `from tag_classifier import classify` (через sys.path.insert) и после каждого INSERT— вызов classify(name, description); если непусто → UPDATE companies SET tags=%s. Try/except обертывание.
- Backup: `full_parser.py.bak-20260425-tags`.
- Verified classify() output: "Каркасные коттеджи под ключ" → [каркас,коттедж,дом_под_ключ]; "Бани+заборы" → [баня,гараж,заборы]; "ИП Иванов услуги" → [].
- Smoke-test после synonym-mapping и manual-tag fix: "Каркасные дома в спб" → total=6 (было 1), СкандиЭкоДом присутствует.
- Cohort анализ 1091 untagged: преимущественно не-строительный шум (Ростелеком, ULab, тендерные площадки, агентства недвижимости) — AI корректно возвращает [].
- TaskList #31 и #32 closed.

### 2026-04-28 — Phase 3: AI re-classify + cleanup + search semantics
- **Step 1 (cleanup)**: 101 descriptions очищены от Yellow Pages мусора (справочная служба, япотечный брокер и т.п.). Backup в `companies.description_orig`.
- **Step 2 (re-classify)**: 3395/3395 companies ре-классифицированы GLM-4.6 за ~2.5ч. Tagged 2275, avg tags 2 (было 1.5). spb_karkas 4 → 9 (+125%). Новые теги: окна_двери=19, кровля=26.
- **Step 3 (search semantics)**: в main.py api_v1_search_companies исправлен стеммер (русские суффиксы 38 окончаний, longest first) и добавлен tag-priority OR (EXISTS tag='<exact>' для таксономии). "Каркасные дома в спб" → 11 (было 6, +83%). Все 9 каркас-Питер компаний в выдаче.
- Backups: scripts/reclassify_all_ai.py, main.py.bak-20260428-tagsearch3.
- TaskList #36, #37, #38 closed.
