PRAGMA foreign_keys = ON;

CREATE TABLE schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at_us INTEGER NOT NULL,
    checksum TEXT NOT NULL
);

CREATE TABLE source_generations (
    source_generation_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    source_scope TEXT NOT NULL CHECK (source_scope IN ('site', 'global')),
    owner_site_id TEXT,
    logical_role TEXT NOT NULL,
    source_identity_fingerprint TEXT,
    source_identity_strength TEXT NOT NULL CHECK (
        source_identity_strength IN ('strong', 'medium', 'weak', 'uncertain')
    ),
    source_identity_provenance TEXT NOT NULL,
    source_resolution_kind TEXT NOT NULL CHECK (
        source_resolution_kind IN ('event_stream', 'native_bucket', 'unknown')
    ),
    source_resolution_seconds INTEGER,
    timezone_state TEXT NOT NULL CHECK (
        timezone_state IN ('verified', 'migrated_unverified', 'unknown')
    ),
    valid_from_us INTEGER,
    valid_to_us INTEGER,
    created_at_us INTEGER NOT NULL,
    CHECK ((source_scope = 'global' AND owner_site_id IS NULL)
        OR (source_scope = 'site' AND owner_site_id IS NOT NULL)),
    CHECK (source_identity_strength = 'uncertain'
        OR source_identity_fingerprint IS NOT NULL),
    CHECK (source_resolution_seconds IS NULL OR source_resolution_seconds > 0),
    CHECK (valid_to_us IS NULL OR valid_from_us IS NULL OR valid_to_us > valid_from_us)
);

CREATE TABLE energy_observations (
    record_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    dataset_version INTEGER NOT NULL,
    semantic_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    supersedes_record_id TEXT,
    site_id TEXT NOT NULL,
    logical_role TEXT NOT NULL,
    source_generation_id TEXT NOT NULL REFERENCES source_generations(source_generation_id),
    interval_start_us INTEGER NOT NULL,
    interval_end_us INTEGER NOT NULL,
    resolution_seconds INTEGER NOT NULL CHECK (resolution_seconds = 900),
    source_resolution_kind TEXT NOT NULL CHECK (
        source_resolution_kind IN ('event_stream', 'native_bucket', 'unknown')
    ),
    source_resolution_seconds INTEGER,
    observed_at_us INTEGER,
    captured_at_us INTEGER NOT NULL,
    fetched_at_us INTEGER,
    known_at_us INTEGER NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('measured', 'derived')),
    value REAL,
    unit TEXT NOT NULL,
    sign_convention TEXT NOT NULL,
    quality_status TEXT NOT NULL CHECK (quality_status IN ('good', 'partial', 'invalid', 'unknown')),
    coverage_ratio REAL CHECK (coverage_ratio IS NULL OR (coverage_ratio >= 0 AND coverage_ratio <= 1)),
    gap_status TEXT NOT NULL CHECK (gap_status IN ('none', 'gap', 'unavailable', 'stale', 'unknown')),
    quality_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    UNIQUE (semantic_key, revision),
    CHECK (interval_end_us = interval_start_us + 900000000),
    CHECK (known_at_us >= captured_at_us),
    CHECK (fetched_at_us IS NULL OR known_at_us >= fetched_at_us)
);

CREATE TABLE historical_energy_observations (
    record_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    dataset_version INTEGER NOT NULL,
    semantic_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    supersedes_record_id TEXT,
    site_id TEXT NOT NULL,
    logical_role TEXT NOT NULL,
    source_generation_id TEXT NOT NULL REFERENCES source_generations(source_generation_id),
    interval_start_us INTEGER NOT NULL,
    interval_end_us INTEGER NOT NULL,
    resolution_seconds INTEGER NOT NULL CHECK (resolution_seconds > 0),
    source_resolution_kind TEXT NOT NULL CHECK (
        source_resolution_kind IN ('event_stream', 'native_bucket', 'unknown')
    ),
    source_resolution_seconds INTEGER NOT NULL CHECK (source_resolution_seconds > 0),
    observed_at_us INTEGER,
    captured_at_us INTEGER NOT NULL,
    fetched_at_us INTEGER,
    known_at_us INTEGER NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN ('measured', 'derived')),
    value REAL,
    unit TEXT NOT NULL,
    sign_convention TEXT NOT NULL,
    quality_status TEXT NOT NULL CHECK (quality_status IN ('good', 'partial', 'invalid', 'unknown')),
    coverage_ratio REAL CHECK (coverage_ratio IS NULL OR (coverage_ratio >= 0 AND coverage_ratio <= 1)),
    gap_status TEXT NOT NULL CHECK (gap_status IN ('none', 'gap', 'unavailable', 'stale', 'unknown')),
    quality_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    UNIQUE (semantic_key, revision),
    CHECK (interval_end_us > interval_start_us),
    CHECK (known_at_us >= captured_at_us),
    CHECK (fetched_at_us IS NULL OR known_at_us >= fetched_at_us)
);

CREATE TABLE external_input_frames (
    frame_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    dataset_version INTEGER NOT NULL,
    semantic_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    supersedes_frame_id TEXT,
    source_generation_id TEXT NOT NULL REFERENCES source_generations(source_generation_id),
    source_scope TEXT NOT NULL CHECK (source_scope IN ('site', 'global')),
    site_id TEXT,
    logical_role TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (
        classification IN ('measured', 'derived', 'estimated', 'forecast', 'published')
    ),
    published_at_us INTEGER,
    fetched_at_us INTEGER,
    known_at_us INTEGER NOT NULL,
    captured_at_us INTEGER NOT NULL,
    valid_from_us INTEGER,
    valid_to_us INTEGER,
    quality_status TEXT NOT NULL CHECK (quality_status IN ('good', 'partial', 'invalid', 'unknown')),
    quality_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    payload_schema TEXT NOT NULL,
    UNIQUE (semantic_key, revision),
    CHECK ((source_scope = 'global' AND site_id IS NULL)
        OR (source_scope = 'site' AND site_id IS NOT NULL)),
    CHECK (known_at_us >= captured_at_us),
    CHECK (fetched_at_us IS NULL OR known_at_us >= fetched_at_us),
    CHECK (valid_to_us IS NULL OR valid_from_us IS NULL OR valid_to_us > valid_from_us)
);

CREATE TABLE external_input_points (
    point_id TEXT PRIMARY KEY,
    frame_id TEXT NOT NULL REFERENCES external_input_frames(frame_id),
    point_key TEXT NOT NULL,
    valid_at_us INTEGER NOT NULL,
    value REAL,
    unit TEXT NOT NULL,
    quality_status TEXT NOT NULL CHECK (quality_status IN ('good', 'partial', 'invalid', 'unknown')),
    point_json TEXT NOT NULL,
    UNIQUE (frame_id, point_key)
);

CREATE INDEX energy_by_site_role_time
    ON energy_observations(site_id, logical_role, interval_start_us);
CREATE INDEX energy_by_generation_time
    ON energy_observations(source_generation_id, interval_start_us);
CREATE INDEX historical_by_site_role_time
    ON historical_energy_observations(site_id, logical_role, interval_start_us);
CREATE INDEX historical_by_generation_time
    ON historical_energy_observations(source_generation_id, interval_start_us);
CREATE INDEX frames_by_scope_role_validity
    ON external_input_frames(source_scope, site_id, logical_role, valid_from_us, valid_to_us);
CREATE INDEX points_by_frame_time
    ON external_input_points(frame_id, valid_at_us);

CREATE TRIGGER energy_immutable_update
BEFORE UPDATE ON energy_observations
BEGIN
    SELECT RAISE(ABORT, 'energy_observations are immutable; insert a revision');
END;
CREATE TRIGGER energy_immutable_delete
BEFORE DELETE ON energy_observations
BEGIN
    SELECT RAISE(ABORT, 'energy_observations are immutable');
END;
CREATE TRIGGER historical_immutable_update
BEFORE UPDATE ON historical_energy_observations
BEGIN
    SELECT RAISE(ABORT, 'historical_energy_observations are immutable; insert a revision');
END;
CREATE TRIGGER historical_immutable_delete
BEFORE DELETE ON historical_energy_observations
BEGIN
    SELECT RAISE(ABORT, 'historical_energy_observations are immutable');
END;
CREATE TRIGGER frame_immutable_update
BEFORE UPDATE ON external_input_frames
BEGIN
    SELECT RAISE(ABORT, 'external_input_frames are immutable; insert a revision');
END;
CREATE TRIGGER frame_immutable_delete
BEFORE DELETE ON external_input_frames
BEGIN
    SELECT RAISE(ABORT, 'external_input_frames are immutable');
END;
CREATE TRIGGER energy_supersedes_same_semantic
BEFORE INSERT ON energy_observations
WHEN NEW.supersedes_record_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'supersedes_record_id must reference the same semantic key')
    WHERE NOT EXISTS (
        SELECT 1 FROM energy_observations
        WHERE record_id = NEW.supersedes_record_id AND semantic_key = NEW.semantic_key
    );
END;
CREATE TRIGGER historical_supersedes_same_semantic
BEFORE INSERT ON historical_energy_observations
WHEN NEW.supersedes_record_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'supersedes_record_id must reference the same semantic key')
    WHERE NOT EXISTS (
        SELECT 1 FROM historical_energy_observations
        WHERE record_id = NEW.supersedes_record_id AND semantic_key = NEW.semantic_key
    );
END;
CREATE TRIGGER frame_supersedes_same_semantic
BEFORE INSERT ON external_input_frames
WHEN NEW.supersedes_frame_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'supersedes_frame_id must reference the same semantic key')
    WHERE NOT EXISTS (
        SELECT 1 FROM external_input_frames
        WHERE frame_id = NEW.supersedes_frame_id AND semantic_key = NEW.semantic_key
    );
END;
