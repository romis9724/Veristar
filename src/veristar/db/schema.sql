-- Veristar PostgreSQL + pgvector 스키마
-- 온톨로지 models.py 구조를 1:1 반영

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─── 엔티티 ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,           -- EntityType enum
    name        TEXT NOT NULL,
    aliases     TEXT[]       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL,
    -- 타입별 추가 속성 (Person: birth_year/nationality, Group: debut_date, ...)
    extra       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    -- nomic-embed-text: 768 dims
    embedding   vector(768)
);

CREATE INDEX IF NOT EXISTS idx_entities_type      ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name_trgm ON entities USING gin(name gin_trgm_ops);
-- 벡터 인덱스: 최소 100개 이상 행이 있어야 효율적 (소규모엔 sequential scan이 빠름)
-- CREATE INDEX idx_entities_vec ON entities USING ivfflat (embedding vector_cosine_ops);

-- ─── 출처 ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sources (
    id           TEXT PRIMARY KEY,
    source_type  TEXT    NOT NULL,       -- SourceType enum
    publisher    TEXT    NOT NULL,
    url          TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    published_at DATE,
    retrieved_at DATE,
    license      TEXT,
    extra        JSONB   NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sources_source_type ON sources(source_type);

-- ─── Statement (reified edge) ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS statements (
    id          TEXT PRIMARY KEY,
    subject     TEXT    NOT NULL,        -- entities.id (soft ref; 외부 QID 허용)
    predicate   TEXT    NOT NULL,        -- Predicate enum
    object      TEXT    NOT NULL,        -- entities.id (soft ref)
    grade       TEXT    NOT NULL,        -- Grade enum
    status      TEXT    NOT NULL DEFAULT 'ACTIVE',
    sources     TEXT[]  NOT NULL,        -- source ids
    valid_from  DATE,
    valid_to    DATE,
    asserted_at DATE,
    sensitive   BOOLEAN NOT NULL DEFAULT FALSE,
    qualifier   TEXT
);

CREATE INDEX IF NOT EXISTS idx_statements_subject   ON statements(subject);
CREATE INDEX IF NOT EXISTS idx_statements_object    ON statements(object);
CREATE INDEX IF NOT EXISTS idx_statements_grade     ON statements(grade);
CREATE INDEX IF NOT EXISTS idx_statements_status    ON statements(status);
CREATE INDEX IF NOT EXISTS idx_statements_predicate ON statements(predicate);

-- ─── Vault docs (raw 수집 콘텐츠) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vault_docs (
    id           TEXT PRIMARY KEY,
    title        TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    source_type  TEXT    NOT NULL,
    source_url   TEXT    NOT NULL,
    entity_refs  TEXT[]  NOT NULL DEFAULT '{}',
    published    DATE,
    retrieved    DATE,
    confidence   TEXT    NOT NULL DEFAULT 'unverified',
    license      TEXT,
    sensitive    BOOLEAN NOT NULL DEFAULT FALSE,
    extra        JSONB   NOT NULL DEFAULT '{}'::jsonb,
    -- title + content 앞부분 임베딩 (의미 검색·중복 감지용)
    embedding    vector(768)
);

CREATE INDEX IF NOT EXISTS idx_vault_docs_source_type ON vault_docs(source_type);
CREATE INDEX IF NOT EXISTS idx_vault_docs_confidence  ON vault_docs(confidence);
CREATE INDEX IF NOT EXISTS idx_vault_docs_sensitive   ON vault_docs(sensitive);
