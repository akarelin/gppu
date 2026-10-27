-- Linked Data's standard (_Standards/Linked Data/Linked Data.md), its schemas ld and fs, copied verbatim for the tests.

CREATE SCHEMA ld;

-- id: shard, then 7 header bytes of 0, then 6 bytes of uuidv7 time and 2 random
CREATE FUNCTION ld.uuid_create(shard int)
RETURNS uuid
LANGUAGE sql
VOLATILE
AS $$
    SELECT encode(set_byte('\x0000000000000000'::bytea, 0, shard) || substring(v7 FROM 1 FOR 6) || substring(v7 FROM 11 FOR 2), 'hex')::uuid
    FROM (SELECT uuid_send(uuidv7()) AS v7) AS s;
$$;

CREATE TABLE ld.records (
    id        uuid,
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
    CHECK (false) NO INHERIT
);

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
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'00'::int),
    slug      text NOT NULL,
    shard     smallint NOT NULL,
    UNIQUE (shard, slug)
) INHERITS (ld.records);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON ld.types FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE PROCEDURE ld.type_create(slug text, shard int, name text, parent text DEFAULT NULL,
                                  flags smallint DEFAULT 0, status text DEFAULT NULL, span tstzrange DEFAULT NULL, data jsonb DEFAULT '{}', meta jsonb DEFAULT '{}')
LANGUAGE sql
AS $$
    INSERT INTO ld.types (slug, shard, name, parent_id, flags, status, span, data, meta)
    VALUES (type_create.slug, type_create.shard, type_create.name,
            (SELECT p.id FROM ld.types p WHERE p.slug = type_create.parent AND p.shard = type_create.shard),
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

CALL ld.type_create(slug => 'type', shard => x'00'::int, name => 'Type');
CALL ld.type_create(slug => 'node', shard => x'01'::int, name => 'Node');
CALL ld.type_create(slug => 'link', shard => x'02'::int, name => 'Link');
CALL ld.type_create(slug => 'event', shard => x'03'::int, name => 'Event');

CREATE TABLE ld.links (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'02'::int),
    from_id   uuid,
    to_id     uuid
) INHERITS (ld.records);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON ld.links FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE ld.nodes (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'01'::int)
) INHERITS (ld.records);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON ld.nodes FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE ld.events (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'03'::int)
) INHERITS (ld.records);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON ld.events FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL ld.type_create(slug => 'activity', shard => x'03'::int, name => 'Activity', parent => 'event');

CREATE SCHEMA fs;

CREATE TABLE fs.types (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'10'::int),
    UNIQUE (shard, slug)
) INHERITS (ld.types);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON fs.types FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE PROCEDURE fs.type_create(slug text, shard int, name text, parent text DEFAULT NULL,
                                  flags smallint DEFAULT 0, status text DEFAULT NULL, span tstzrange DEFAULT NULL, data jsonb DEFAULT '{}', meta jsonb DEFAULT '{}')
LANGUAGE sql
AS $$
    INSERT INTO fs.types (slug, shard, name, parent_id, flags, status, span, data, meta)
    VALUES (type_create.slug, type_create.shard, type_create.name,
            (SELECT p.id FROM fs.types p WHERE p.slug = type_create.parent AND p.shard = type_create.shard),
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

CALL fs.type_create(slug => 'location', shard => x'11'::int, name => 'Location');
CALL fs.type_create(slug => 'provider', shard => x'11'::int, name => 'Provider');
CALL fs.type_create(slug => 'file', shard => x'13'::int, name => 'File', data => '{"class": "gppu.fs.handlers.FileHandler"}');
CALL fs.type_create(slug => 'instance', shard => x'14'::int, name => 'Instance');

CALL fs.status_create(slug => 'parsed', shard => x'13'::int, name => 'Parsed', type => 'file');
CALL fs.status_create(slug => 'unread', shard => x'13'::int, name => 'Unread', type => 'file');

CREATE TABLE fs.locations (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'11'::int),
    provider  text,
    service   text
) INHERITS (ld.records);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON fs.locations FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL fs.type_create(slug => 'file_system', shard => x'11'::int, name => 'File system', parent => 'provider', data => '{"class": "gppu.fs.FileSystem"}');
CALL fs.type_create(slug => 'm365', shard => x'11'::int, name => 'M365', parent => 'provider', data => '{"class": "lake.providers.m365.M365"}');
CALL fs.type_create(slug => 'plaud', shard => x'11'::int, name => 'Plaud', parent => 'provider', data => '{"class": "lake.providers.plaud.Plaud"}');
CALL fs.type_create(slug => 'telegram', shard => x'11'::int, name => 'Telegram', parent => 'provider', data => '{"class": "lake.providers.telegram.Telegram"}');

CREATE TABLE fs.files (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'13'::int)
) INHERITS (ld.records);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON fs.files FOR EACH ROW EXECUTE FUNCTION ld.record();

CALL fs.type_create(slug => 'folder', shard => x'13'::int, name => 'Folder', parent => 'file', data => '{"class": "gppu.fs.handlers.FolderHandler"}');

CALL fs.type_create(slug => 'work', shard => x'13'::int, name => 'Work', parent => 'folder', data => '{"class": "gppu.fs.handlers.WorkFolderHandler"}');
CALL fs.type_create(slug => 'projects', shard => x'13'::int, name => 'Projects', parent => 'folder', data => '{"class": "gppu.fs.handlers.ProjectsFolderHandler"}');
CALL fs.type_create(slug => 'sessionfolder', shard => x'13'::int, name => 'Session folder', parent => 'folder', data => '{"class": "gppu.fs.handlers.SessionFolderHandler"}');

CALL fs.type_create(slug => 'sqlite', shard => x'13'::int, name => 'SQLite', parent => 'file', data => '{"class": "gppu.fs.handlers.SqliteHandler"}');
CALL fs.type_create(slug => 'markdown', shard => x'13'::int, name => 'Markdown', parent => 'file', data => '{"class": "gppu.fs.handlers.MarkdownHandler"}');
CALL fs.type_create(slug => 'csv', shard => x'13'::int, name => 'CSV', parent => 'file', data => '{"class": "gppu.fs.handlers.CSVHandler"}');
CALL fs.type_create(slug => 'log', shard => x'13'::int, name => 'Log', parent => 'file', data => '{"class": "gppu.fs.handlers.LogHandler"}');
CALL fs.type_create(slug => 'email', shard => x'13'::int, name => 'Email', parent => 'file', data => '{"class": "gppu.fs.handlers.EmailHandler"}');
CALL fs.type_create(slug => 'export', shard => x'13'::int, name => 'Export', parent => 'file', data => '{"class": "gppu.fs.handlers.ExportHandler"}');
CALL fs.type_create(slug => 'session', shard => x'13'::int, name => 'Session', parent => 'file', data => '{"class": "gppu.fs.handlers.SessionHandler"}');

CALL fs.type_create(slug => 'symlink', shard => x'13'::int, name => 'Link', parent => 'file');
CALL fs.type_create(slug => 'junction', shard => x'13'::int, name => 'Junction', parent => 'file');
CALL fs.type_create(slug => 'offline', shard => x'13'::int, name => 'Offline', parent => 'file');
CALL fs.type_create(slug => 'ignored', shard => x'13'::int, name => 'Ignored', parent => 'file');

CREATE TABLE fs.instances (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'14'::int)
) INHERITS (ld.records);
CREATE TRIGGER record BEFORE INSERT OR UPDATE ON fs.instances FOR EACH ROW EXECUTE FUNCTION ld.record();
