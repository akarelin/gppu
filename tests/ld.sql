-- gppu.ld's tables, schemas ld, fs and sessions, each table with a record's columns of its own and no parent, to Linked Data's standard (_Standards/Linked Data/Linked Data.md); the tests make their database from it.

CREATE SCHEMA ld;

-- id: the shard in two bytes (shard1, shard2), version 1, 5 reserved bytes of 0, then 6 bytes of uuidv7 time and 2 random
CREATE FUNCTION ld.uuid_create(shard int)
RETURNS uuid
LANGUAGE sql
VOLATILE
AS $$
    SELECT encode(substring(int4send(shard) FROM 3 FOR 2) || '\x010000000000'::bytea || substring(v7 FROM 1 FOR 6) || substring(v7 FROM 11 FOR 2), 'hex')::uuid
    FROM (SELECT uuid_send(uuidv7()) AS v7) AS s;
$$;

CREATE FUNCTION ld.record()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.name IS NOT DISTINCT FROM OLD.name AND OLD.name = coalesce(OLD.data->>'name', OLD.type || '-' || OLD.id) THEN
            NEW.name := NULL;
        END IF;
        NEW.updated := now();
    END IF;
    NEW.name := coalesce(NEW.name, NEW.data->>'name', NEW.type || '-' || NEW.id);
    RETURN NEW;
END;
$$;

CREATE TABLE ld.types (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'0000'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    slug      text NOT NULL,
    shard     integer NOT NULL,     -- the shard of the table its records are in, two bytes: shard1 its schema, shard2 the table
    UNIQUE (shard, slug)
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON ld.types FOR EACH ROW EXECUTE FUNCTION ld.record();

-- parent is the type of `ld` it is under (Linked Data, # Types); `type` has none
CREATE PROCEDURE ld.type_create(slug text, shard int, name text, parent text DEFAULT NULL,
                                  flags smallint DEFAULT 0, status text DEFAULT NULL, span tstzrange DEFAULT NULL, data jsonb DEFAULT '{}', meta jsonb DEFAULT '{}')
LANGUAGE sql
AS $$
    INSERT INTO ld.types (slug, shard, name, parent_id, flags, status, span, data, meta)
    VALUES (type_create.slug, type_create.shard, type_create.name,
            (SELECT p.id FROM ld.types p WHERE p.slug = type_create.parent AND p.type IS NULL),
            type_create.flags, type_create.status, type_create.span, type_create.data, type_create.meta);
$$;

-- a status is a row of type 'status' whose parent is the type it belongs to
CREATE PROCEDURE ld.status_create(slug text, shard int, name text, type text,
                                    flags smallint DEFAULT 0, status text DEFAULT NULL, span tstzrange DEFAULT NULL, data jsonb DEFAULT '{}', meta jsonb DEFAULT '{}')
LANGUAGE sql
AS $$
    INSERT INTO ld.types (type, slug, shard, name, parent_id, flags, status, span, data, meta)
    VALUES ('status', status_create.slug, status_create.shard, status_create.name,
            (SELECT t.id FROM ld.types t WHERE t.slug = status_create.type AND t.shard = status_create.shard),
            status_create.flags, status_create.status, status_create.span, status_create.data, status_create.meta);
$$;

CALL ld.type_create(slug => 'type', shard => x'0000'::int, name => 'Type');
CALL ld.type_create(slug => 'node', shard => x'0001'::int, name => 'Node', parent => 'type');
CALL ld.type_create(slug => 'link', shard => x'0010'::int, name => 'Link', parent => 'type');
CALL ld.type_create(slug => 'event', shard => x'0020'::int, name => 'Event', parent => 'node');

CREATE TABLE ld.links (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'0010'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    from_id   uuid,
    to_id     uuid
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON ld.links FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL ld.type_create(slug => 'related', shard => x'0010'::int, name => 'Related', parent => 'link');
CALL ld.type_create(slug => 'same', shard => x'0010'::int, name => 'Same', parent => 'link');
CALL ld.type_create(slug => 'up', shard => x'0010'::int, name => 'Up', parent => 'link');
CALL ld.type_create(slug => 'down', shard => x'0010'::int, name => 'Down', parent => 'link');
CALL ld.type_create(slug => 'prev', shard => x'0010'::int, name => 'Prev', parent => 'link');
CALL ld.type_create(slug => 'next', shard => x'0010'::int, name => 'Next', parent => 'link');
CALL ld.type_create(slug => 'prov-o', shard => x'0010'::int, name => 'PROV-O', parent => 'link');
CALL ld.type_create(slug => 'generated-by', shard => x'0010'::int, name => 'wasGeneratedBy', parent => 'prov-o');
CALL ld.type_create(slug => 'derived-from', shard => x'0010'::int, name => 'wasDerivedFrom', parent => 'prov-o');
CALL ld.type_create(slug => 'attributed-to', shard => x'0010'::int, name => 'wasAttributedTo', parent => 'prov-o');
CALL ld.type_create(slug => 'associated-with', shard => x'0010'::int, name => 'wasAssociatedWith', parent => 'prov-o');
CALL ld.type_create(slug => 'informed-by', shard => x'0010'::int, name => 'wasInformedBy', parent => 'prov-o');
CALL ld.type_create(slug => 'started-by', shard => x'0010'::int, name => 'wasStartedBy', parent => 'prov-o');
CALL ld.type_create(slug => 'invalidated-by', shard => x'0010'::int, name => 'wasInvalidatedBy', parent => 'prov-o');
CALL ld.type_create(slug => 'ended-by', shard => x'0010'::int, name => 'wasEndedBy', parent => 'prov-o');

CREATE TABLE ld.nodes (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'0001'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON ld.nodes FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL ld.type_create(slug => 'entity', shard => x'0001'::int, name => 'Entity', parent => 'node');
CALL ld.type_create(slug => 'content', shard => x'0001'::int, name => 'Content', parent => 'node');
CALL ld.type_create(slug => 'resource', shard => x'0001'::int, name => 'URI', parent => 'entity');
CALL ld.type_create(slug => 'resource-fragment', shard => x'0001'::int, name => 'Resource fragment', parent => 'resource');
CALL ld.type_create(slug => 'skos-cs', shard => x'0001'::int, name => 'skos:ConceptScheme', parent => 'entity');
CALL ld.type_create(slug => 'onto-cv', shard => x'0001'::int, name => 'Controlled Vocabulary', parent => 'skos-cs');
CALL ld.type_create(slug => 'label', shard => x'0001'::int, name => 'Label', parent => 'onto-cv');
CALL ld.type_create(slug => 'dimension', shard => x'0001'::int, name => 'Label used as 1st division', parent => 'label');
CALL ld.type_create(slug => 'axis', shard => x'0001'::int, name => 'Axis', parent => 'dimension');
CALL ld.type_create(slug => 'theme', shard => x'0001'::int, name => 'Theme', parent => 'label');
CALL ld.type_create(slug => 'status', shard => x'0001'::int, name => 'Status', parent => 'label');
CALL ld.type_create(slug => 'ne', shard => x'0001'::int, name => 'Named Entity', parent => 'entity');
CALL ld.type_create(slug => 'idea', shard => x'0001'::int, name => 'Idea', parent => 'entity');
CALL ld.type_create(slug => 'container', shard => x'0001'::int, name => 'Container', parent => 'node');
CALL ld.type_create(slug => 'collection', shard => x'0001'::int, name => 'Collection', parent => 'node');
CALL ld.type_create(slug => 'view', shard => x'0001'::int, name => 'View', parent => 'node');
CALL ld.type_create(slug => 'knowledge', shard => x'0001'::int, name => 'Knowledge', parent => 'node');

CALL ld.status_create(slug => 'entity-status', shard => x'0001'::int, name => 'Status', type => 'entity');
CALL ld.status_create(slug => 'new', shard => x'0001'::int, name => 'New', type => 'entity-status');
CALL ld.status_create(slug => 'active', shard => x'0001'::int, name => 'Active', type => 'entity-status');
CALL ld.status_create(slug => 'rejected', shard => x'0001'::int, name => 'Rejected', type => 'entity-status');

CREATE TABLE ld.events (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'0020'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON ld.events FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL ld.type_create(slug => 'activity', shard => x'0020'::int, name => 'Activity', parent => 'event');
CALL ld.type_create(slug => 'message', shard => x'0020'::int, name => 'Message', parent => 'event');
CALL ld.type_create(slug => 'work', shard => x'0020'::int, name => 'Real Activity', parent => 'activity');
CALL ld.type_create(slug => 'epic', shard => x'0020'::int, name => 'Epic', parent => 'work');
CALL ld.type_create(slug => 'project', shard => x'0020'::int, name => 'Project', parent => 'work');
CALL ld.type_create(slug => 'task', shard => x'0020'::int, name => 'Task', parent => 'work');
CALL ld.type_create(slug => 'project-experiment', shard => x'0020'::int, name => 'Experiment', parent => 'project');
CALL ld.type_create(slug => 'task-experiment', shard => x'0020'::int, name => 'Experiment', parent => 'task');
CALL ld.type_create(slug => 'project-feature', shard => x'0020'::int, name => 'Feature', parent => 'project');
CALL ld.type_create(slug => 'epic-feature', shard => x'0020'::int, name => 'Feature', parent => 'epic');
CALL ld.type_create(slug => 'task-feature', shard => x'0020'::int, name => 'Feature', parent => 'task');
CALL ld.type_create(slug => 'problem', shard => x'0020'::int, name => 'Problem', parent => 'task');
CALL ld.type_create(slug => 'chore', shard => x'0020'::int, name => 'Chore', parent => 'task');

CALL ld.status_create(slug => 'work-status', shard => x'0020'::int, name => 'Status', type => 'work');
CALL ld.status_create(slug => 'proposed', shard => x'0020'::int, name => NULL, type => 'work-status');
CALL ld.status_create(slug => 'planned', shard => x'0020'::int, name => NULL, type => 'work-status');
CALL ld.status_create(slug => 'active', shard => x'0020'::int, name => NULL, type => 'work-status');
CALL ld.status_create(slug => 'pending', shard => x'0020'::int, name => NULL, type => 'work-status');
CALL ld.status_create(slug => 'suspended', shard => x'0020'::int, name => NULL, type => 'work-status');
CALL ld.status_create(slug => 'completed', shard => x'0020'::int, name => NULL, type => 'work-status');
CALL ld.status_create(slug => 'abandoned', shard => x'0020'::int, name => NULL, type => 'work-status');
CALL ld.status_create(slug => 'rejected', shard => x'0020'::int, name => NULL, type => 'work-status');

CREATE SCHEMA fs;

CREATE TABLE fs.types (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'1000'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    slug      text NOT NULL,
    shard     integer NOT NULL,     -- the shard of the table its records are in, two bytes: shard1 its schema, shard2 the table
    UNIQUE (shard, slug)
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON fs.types FOR EACH ROW EXECUTE FUNCTION ld.record();

-- parent is the type of `fs` it is under; a root type has none and says what one of the schema's tables holds
CREATE PROCEDURE fs.type_create(slug text, shard int, name text, parent text DEFAULT NULL,
                                  flags smallint DEFAULT 0, status text DEFAULT NULL, span tstzrange DEFAULT NULL, data jsonb DEFAULT '{}', meta jsonb DEFAULT '{}')
LANGUAGE sql
AS $$
    INSERT INTO fs.types (slug, shard, name, parent_id, flags, status, span, data, meta)
    VALUES (type_create.slug, type_create.shard, type_create.name,
            (SELECT p.id FROM fs.types p WHERE p.slug = type_create.parent AND p.type IS NULL),
            type_create.flags, type_create.status, type_create.span, type_create.data, type_create.meta);
$$;

CREATE PROCEDURE fs.status_create(slug text, shard int, name text, type text,
                                    flags smallint DEFAULT 0, status text DEFAULT NULL, span tstzrange DEFAULT NULL, data jsonb DEFAULT '{}', meta jsonb DEFAULT '{}')
LANGUAGE sql
AS $$
    INSERT INTO fs.types (type, slug, shard, name, parent_id, flags, status, span, data, meta)
    VALUES ('status', status_create.slug, status_create.shard, status_create.name,
            (SELECT t.id FROM fs.types t WHERE t.slug = status_create.type AND t.shard = status_create.shard),
            status_create.flags, status_create.status, status_create.span, status_create.data, status_create.meta);
$$;

CALL fs.type_create(slug => 'location', shard => x'1001'::int, name => 'Location');
CALL fs.type_create(slug => 'file', shard => x'1002'::int, name => 'File', data => '{"class": "gppu.fs.handlers.FileHandler"}');
CALL fs.type_create(slug => 'instance', shard => x'1003'::int, name => 'Instance');

CALL fs.status_create(slug => 'active', shard => x'1001'::int, name => 'Active', type => 'location');
CALL fs.status_create(slug => 'discarded', shard => x'1001'::int, name => 'Discarded', type => 'location');
CALL fs.status_create(slug => 'parsed', shard => x'1002'::int, name => 'Parsed', type => 'file');

CREATE TABLE fs.locations (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'1001'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON fs.locations FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL fs.type_create(slug => 'host', shard => x'1001'::int, name => 'Host', parent => 'location');

CREATE TABLE fs.files (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'1002'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON fs.files FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL fs.type_create(slug => 'folder', shard => x'1002'::int, name => 'Folder', parent => 'file', data => '{"class": "gppu.fs.handlers.FolderHandler"}');

CALL fs.type_create(slug => 'work', shard => x'1002'::int, name => 'Work', parent => 'folder', data => '{"class": "gppu.fs.handlers.WorkFolderHandler"}');
CALL fs.type_create(slug => 'projects', shard => x'1002'::int, name => 'Projects', parent => 'folder', data => '{"class": "gppu.fs.handlers.ProjectsFolderHandler"}');
CALL fs.type_create(slug => 'sessionfolder', shard => x'1002'::int, name => 'Session folder', parent => 'folder', data => '{"class": "gppu.fs.handlers.SessionFolderHandler"}');

CALL fs.type_create(slug => 'sqlite', shard => x'1002'::int, name => 'SQLite', parent => 'file', data => '{"class": "gppu.fs.handlers.SqliteHandler"}');
CALL fs.type_create(slug => 'markdown', shard => x'1002'::int, name => 'Markdown', parent => 'file', data => '{"class": "gppu.fs.handlers.MarkdownHandler"}');
CALL fs.type_create(slug => 'csv', shard => x'1002'::int, name => 'CSV', parent => 'file', data => '{"class": "gppu.fs.handlers.CSVHandler"}');
CALL fs.type_create(slug => 'log', shard => x'1002'::int, name => 'Log', parent => 'file', data => '{"class": "gppu.fs.handlers.LogHandler"}');
CALL fs.type_create(slug => 'email', shard => x'1002'::int, name => 'Email', parent => 'file', data => '{"class": "gppu.fs.handlers.EmailHandler"}');
CALL fs.type_create(slug => 'export', shard => x'1002'::int, name => 'Export', parent => 'file', data => '{"class": "gppu.fs.handlers.ExportHandler"}');
CALL fs.type_create(slug => 'session', shard => x'1002'::int, name => 'Session', parent => 'file', data => '{"class": "gppu.fs.handlers.SessionHandler"}');
CALL fs.type_create(slug => 'archive', shard => x'1002'::int, name => 'Archive', parent => 'file');

CALL fs.type_create(slug => 'cc', shard => x'1002'::int, name => 'Claude Code', parent => 'session');
CALL fs.type_create(slug => 'cx', shard => x'1002'::int, name => 'Codex', parent => 'session');
CALL fs.type_create(slug => 'gemini', shard => x'1002'::int, name => 'Gemini', parent => 'session');
CALL fs.type_create(slug => 'openclaw', shard => x'1002'::int, name => 'OpenClaw', parent => 'session');
CALL fs.type_create(slug => 'agy', shard => x'1002'::int, name => 'Antigravity', parent => 'session');
CALL fs.type_create(slug => 'hermes', shard => x'1002'::int, name => 'Hermes', parent => 'session');

CALL fs.type_create(slug => 'symlink', shard => x'1002'::int, name => 'Symlink', parent => 'file');
CALL fs.type_create(slug => 'junction', shard => x'1002'::int, name => 'Junction', parent => 'file');
CALL fs.type_create(slug => 'offline', shard => x'1002'::int, name => 'Offline', parent => 'file');
CALL fs.type_create(slug => 'ignored', shard => x'1002'::int, name => 'Ignored', parent => 'file');
CALL fs.type_create(slug => 'normal', shard => x'1002'::int, name => 'Normal', parent => 'file');

CREATE TABLE fs.instances (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'1003'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON fs.instances FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE fs.links (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'1010'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    from_id   uuid,
    to_id     uuid
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON fs.links FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL fs.type_create(slug => 'link', shard => x'1010'::int, name => 'Link');

CREATE SCHEMA sessions;

CREATE TABLE sessions.types (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'2000'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    slug      text NOT NULL,
    shard     integer NOT NULL,     -- the shard of the table its records are in, two bytes: shard1 its schema, shard2 the table
    UNIQUE (shard, slug)
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON sessions.types FOR EACH ROW EXECUTE FUNCTION ld.record();

-- parent is the type of `sessions` it is under; a root type has none and says what one of the schema's tables holds
CREATE PROCEDURE sessions.type_create(slug text, shard int, name text, parent text DEFAULT NULL,
                                        flags smallint DEFAULT 0, status text DEFAULT NULL, span tstzrange DEFAULT NULL, data jsonb DEFAULT '{}', meta jsonb DEFAULT '{}')
LANGUAGE sql
AS $$
    INSERT INTO sessions.types (slug, shard, name, parent_id, flags, status, span, data, meta)
    VALUES (type_create.slug, type_create.shard, type_create.name,
            (SELECT p.id FROM sessions.types p WHERE p.slug = type_create.parent AND p.type IS NULL),
            type_create.flags, type_create.status, type_create.span, type_create.data, type_create.meta);
$$;

CREATE PROCEDURE sessions.status_create(slug text, shard int, name text, type text,
                                          flags smallint DEFAULT 0, status text DEFAULT NULL, span tstzrange DEFAULT NULL, data jsonb DEFAULT '{}', meta jsonb DEFAULT '{}')
LANGUAGE sql
AS $$
    INSERT INTO sessions.types (type, slug, shard, name, parent_id, flags, status, span, data, meta)
    VALUES ('status', status_create.slug, status_create.shard, status_create.name,
            (SELECT t.id FROM sessions.types t WHERE t.slug = status_create.type AND t.shard = status_create.shard),
            status_create.flags, status_create.status, status_create.span, status_create.data, status_create.meta);
$$;

CALL sessions.type_create(slug => 'session', shard => x'2001'::int, name => 'Session');
CALL sessions.type_create(slug => 'message', shard => x'2002'::int, name => 'Message');
CALL sessions.type_create(slug => 'link', shard => x'2010'::int, name => 'Link');

CALL sessions.status_create(slug => 'active', shard => x'2001'::int, name => 'Active', type => 'session');
CALL sessions.status_create(slug => 'completed', shard => x'2001'::int, name => 'Completed', type => 'session');
CALL sessions.status_create(slug => 'discarded', shard => x'2001'::int, name => 'Discarded', type => 'session');
CALL sessions.status_create(slug => 'new', shard => x'2010'::int, name => 'New', type => 'link');
CALL sessions.status_create(slug => 'active', shard => x'2010'::int, name => 'Active', type => 'link');

CREATE TABLE sessions.sessions (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'2001'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    uid       text,
    UNIQUE (type, uid)
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON sessions.sessions FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL sessions.type_create(slug => 'cc', shard => x'2001'::int, name => 'Claude Code', parent => 'session');
CALL sessions.type_create(slug => 'cx', shard => x'2001'::int, name => 'Codex', parent => 'session');
CALL sessions.type_create(slug => 'gemini', shard => x'2001'::int, name => 'Gemini', parent => 'session');
CALL sessions.type_create(slug => 'openclaw', shard => x'2001'::int, name => 'OpenClaw', parent => 'session');
CALL sessions.type_create(slug => 'agy', shard => x'2001'::int, name => 'Antigravity', parent => 'session');
CALL sessions.type_create(slug => 'hermes', shard => x'2001'::int, name => 'Hermes', parent => 'session');
CALL sessions.type_create(slug => 'openviking', shard => x'2001'::int, name => 'OpenViking', parent => 'session');
CALL sessions.type_create(slug => 'copilot', shard => x'2001'::int, name => 'Copilot', parent => 'session');

CREATE TABLE sessions.messages (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'2002'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE INDEX ON sessions.messages (parent_id);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON sessions.messages FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL sessions.type_create(slug => 'user', shard => x'2002'::int, name => 'User', parent => 'message');
CALL sessions.type_create(slug => 'agent', shard => x'2002'::int, name => 'Agent', parent => 'message');
CALL sessions.type_create(slug => 'thinking', shard => x'2002'::int, name => 'Thinking', parent => 'message');
CALL sessions.type_create(slug => 'tool_use', shard => x'2002'::int, name => 'Tool use', parent => 'message');
CALL sessions.type_create(slug => 'tool_result', shard => x'2002'::int, name => 'Tool result', parent => 'message');

CREATE TABLE sessions.links (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'2010'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text,
    name      text,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) VIRTUAL,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    from_id   uuid,
    to_id     uuid
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON sessions.links FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL sessions.type_create(slug => 'next', shard => x'2010'::int, name => 'Next', parent => 'link');
