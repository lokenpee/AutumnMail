PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT '163' CHECK (provider IN ('163', 'qq', 'gmail', 'outlook', 'other')),
    email TEXT NOT NULL,
    display_name TEXT,
    credential_ref TEXT NOT NULL,
    imap_host TEXT NOT NULL DEFAULT 'imap.163.com',
    imap_port INTEGER NOT NULL DEFAULT 993 CHECK (imap_port > 0 AND imap_port <= 65535),
    smtp_host TEXT NOT NULL DEFAULT 'smtp.163.com',
    smtp_port INTEGER NOT NULL DEFAULT 465 CHECK (smtp_port > 0 AND smtp_port <= 65535),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'auth_error')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (provider, email)
);

CREATE TABLE IF NOT EXISTS folders (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    delimiter TEXT,
    folder_type TEXT NOT NULL DEFAULT 'custom' CHECK (folder_type IN ('inbox', 'sent', 'drafts', 'trash', 'spam', 'custom')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    uidvalidity TEXT,
    last_uid INTEGER NOT NULL DEFAULT 0 CHECK (last_uid >= 0),
    sync_status TEXT NOT NULL DEFAULT 'pending' CHECK (sync_status IN ('pending', 'syncing', 'ready', 'failed')),
    last_synced_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (account_id, name)
);

CREATE INDEX IF NOT EXISTS idx_folders_account ON folders(account_id);
CREATE INDEX IF NOT EXISTS idx_folders_enabled ON folders(account_id, enabled);

CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    canonical_key TEXT NOT NULL,
    message_id TEXT,
    thread_key TEXT,
    subject TEXT NOT NULL DEFAULT '',
    from_name TEXT,
    from_email TEXT,
    to_json TEXT NOT NULL DEFAULT '[]',
    cc_json TEXT NOT NULL DEFAULT '[]',
    received_at TEXT NOT NULL,
    sent_at TEXT,
    body_text TEXT,
    body_html TEXT,
    snippet TEXT,
    raw_headers_json TEXT,
    has_attachments INTEGER NOT NULL DEFAULT 0 CHECK (has_attachments IN (0, 1)),
    attachment_count INTEGER NOT NULL DEFAULT 0 CHECK (attachment_count >= 0),
    size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    content_hash TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (account_id, canonical_key)
);

CREATE INDEX IF NOT EXISTS idx_emails_received_at ON emails(received_at);
CREATE INDEX IF NOT EXISTS idx_emails_message_id ON emails(message_id);
CREATE INDEX IF NOT EXISTS idx_emails_from_email ON emails(from_email);
CREATE INDEX IF NOT EXISTS idx_emails_thread_key ON emails(thread_key);
CREATE INDEX IF NOT EXISTS idx_emails_content_hash ON emails(content_hash);

CREATE TABLE IF NOT EXISTS email_locations (
    id TEXT PRIMARY KEY,
    email_id TEXT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    folder_id TEXT NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    uid TEXT NOT NULL,
    flags_json TEXT NOT NULL DEFAULT '[]',
    is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
    is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
    source_url TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (folder_id, uid)
);

CREATE INDEX IF NOT EXISTS idx_email_locations_email ON email_locations(email_id);
CREATE INDEX IF NOT EXISTS idx_email_locations_read ON email_locations(is_read);

CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'merged', 'archived')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS company_aliases (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    alias_type TEXT NOT NULL CHECK (alias_type IN ('name', 'domain', 'ats_sender', 'subject_pattern')),
    alias_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'system' CHECK (source IN ('system', 'user')),
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (alias_type, normalized_value)
);

CREATE INDEX IF NOT EXISTS idx_company_aliases_company ON company_aliases(company_id);

CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    location TEXT,
    status TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN ('submitted', 'application_received', 'assessment', 'written_test', 'interview', 'offer', 'rejected', 'no_response', 'unknown')),
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_unique
    ON positions(company_id, normalized_title, COALESCE(location, ''));

CREATE TABLE IF NOT EXISTS email_company_links (
    id TEXT PRIMARY KEY,
    email_id TEXT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    position_id TEXT REFERENCES positions(id) ON DELETE SET NULL,
    link_type TEXT NOT NULL DEFAULT 'candidate' CHECK (link_type IN ('primary', 'mentioned', 'candidate')),
    source TEXT NOT NULL DEFAULT 'rule' CHECK (source IN ('rule', 'model', 'user', 'thread')),
    confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    is_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (is_confirmed IN (0, 1)),
    evidence TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_company_primary
    ON email_company_links(email_id)
    WHERE link_type = 'primary';

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_company_unique
    ON email_company_links(email_id, company_id, COALESCE(position_id, ''), link_type);

CREATE INDEX IF NOT EXISTS idx_email_company_company ON email_company_links(company_id);
CREATE INDEX IF NOT EXISTS idx_email_company_position ON email_company_links(position_id);

CREATE TABLE IF NOT EXISTS classifications (
    id TEXT PRIMARY KEY,
    email_id TEXT NOT NULL UNIQUE REFERENCES emails(id) ON DELETE CASCADE,
    primary_type TEXT NOT NULL CHECK (primary_type IN ('application_received', 'rejected', 'assessment_invite', 'written_test_invite', 'interview_invite', 'offer', 'other', 'unclassified')),
    confidence REAL NOT NULL DEFAULT 0.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    source TEXT NOT NULL DEFAULT 'rule' CHECK (source IN ('rule', 'model', 'user')),
    rule_id TEXT,
    model_version TEXT,
    reason TEXT,
    is_manual_override INTEGER NOT NULL DEFAULT 0 CHECK (is_manual_override IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_classifications_type ON classifications(primary_type);
CREATE INDEX IF NOT EXISTS idx_classifications_confidence ON classifications(confidence);

CREATE TABLE IF NOT EXISTS email_user_states (
    email_id TEXT PRIMARY KEY REFERENCES emails(id) ON DELETE CASCADE,
    is_completed INTEGER NOT NULL DEFAULT 0 CHECK (is_completed IN (0, 1)),
    completed_at TEXT,
    is_ignored INTEGER NOT NULL DEFAULT 0 CHECK (is_ignored IN (0, 1)),
    is_pinned INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1)),
    notes TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS deadlines (
    id TEXT PRIMARY KEY,
    email_id TEXT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    label TEXT,
    due_at_utc TEXT,
    due_date_local TEXT,
    due_time_local TEXT,
    precision TEXT NOT NULL CHECK (precision IN ('date', 'datetime')),
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    source TEXT NOT NULL DEFAULT 'auto' CHECK (source IN ('auto', 'manual')),
    confidence REAL NOT NULL DEFAULT 0.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'cancelled')),
    completed_at TEXT,
    is_manual_override INTEGER NOT NULL DEFAULT 0 CHECK (is_manual_override IN (0, 1)),
    extraction_evidence TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (precision = 'date' AND due_date_local IS NOT NULL)
        OR
        (precision = 'datetime' AND due_at_utc IS NOT NULL AND due_date_local IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_deadlines_email ON deadlines(email_id);
CREATE INDEX IF NOT EXISTS idx_deadlines_due ON deadlines(due_date_local, due_at_utc, status);
CREATE INDEX IF NOT EXISTS idx_deadlines_status ON deadlines(status);

CREATE TABLE IF NOT EXISTS calendar_events (
    id TEXT PRIMARY KEY,
    email_id TEXT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN ('interview', 'deadline', 'other')),
    title TEXT NOT NULL,
    start_at_utc TEXT NOT NULL,
    end_at_utc TEXT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    location TEXT,
    meeting_url TEXT,
    source TEXT NOT NULL DEFAULT 'auto' CHECK (source IN ('auto', 'manual')),
    confidence REAL NOT NULL DEFAULT 0.0 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'completed', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_calendar_events_email ON calendar_events(email_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_start ON calendar_events(start_at_utc, status);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    email_id TEXT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    part_id TEXT NOT NULL,
    filename TEXT,
    mime_type TEXT,
    size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    sha256 TEXT,
    is_inline INTEGER NOT NULL DEFAULT 0 CHECK (is_inline IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (email_id, part_id)
);

CREATE INDEX IF NOT EXISTS idx_attachments_email ON attachments(email_id);

CREATE TABLE IF NOT EXISTS action_links (
    id TEXT PRIMARY KEY,
    email_id TEXT NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    link_type TEXT NOT NULL DEFAULT 'other' CHECK (link_type IN ('assessment', 'written_test', 'interview', 'offer', 'other')),
    label TEXT,
    domain TEXT,
    safety_status TEXT NOT NULL DEFAULT 'unknown' CHECK (safety_status IN ('unknown', 'safe', 'suspicious')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (email_id, normalized_url)
);

CREATE INDEX IF NOT EXISTS idx_action_links_email ON action_links(email_id);
CREATE INDEX IF NOT EXISTS idx_action_links_type ON action_links(link_type);

CREATE TABLE IF NOT EXISTS classification_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    rule_type TEXT NOT NULL CHECK (rule_type IN ('sender', 'subject', 'body', 'domain', 'thread')),
    pattern TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('classification', 'company', 'position', 'deadline')),
    target_value TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'system' CHECK (source IN ('system', 'user')),
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_classification_rules_match
    ON classification_rules(rule_type, target_type, is_enabled, priority);

CREATE TABLE IF NOT EXISTS processing_jobs (
    email_id TEXT PRIMARY KEY REFERENCES emails(id) ON DELETE CASCADE,
    stage TEXT NOT NULL DEFAULT 'imported' CHECK (stage IN ('imported', 'normalized', 'linked', 'classified', 'deadline_extracted', 'review_required', 'ready', 'failed')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs(status, stage);

CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    deadline_id TEXT REFERENCES deadlines(id) ON DELETE CASCADE,
    calendar_event_id TEXT REFERENCES calendar_events(id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('in_app', 'windows', 'email')),
    offset_minutes INTEGER NOT NULL,
    scheduled_at TEXT NOT NULL,
    sent_at TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'sent', 'cancelled', 'failed')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((deadline_id IS NOT NULL) + (calendar_event_id IS NOT NULL) = 1)
);

CREATE INDEX IF NOT EXISTS idx_reminders_scheduled ON reminders(scheduled_at, status);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs(entity_type, entity_id, created_at);

INSERT OR IGNORE INTO schema_migrations(version, description) VALUES (1, 'initial schema');
INSERT OR IGNORE INTO schema_migrations(version, description) VALUES (2, 'allow other classification');
