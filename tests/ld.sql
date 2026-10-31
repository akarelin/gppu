-- gppu.ld's tables, schemas ld, fs and sessions, each table with a record's columns of its own and no parent, to Linked Data's standard 0.3 (_Standards/Linked Data/Linked Data.md); the tests make their database from it.

CREATE SCHEMA ld;
CREATE SCHEMA fs;
CREATE SCHEMA sessions;

-- id: the shard in two bytes (shard1, shard2), version 1, 5 reserved bytes of 0, then 6 bytes of uuidv7 time and 2 random
CREATE FUNCTION ld.uuid_create(shard int)
RETURNS uuid
LANGUAGE sql
VOLATILE
AS $$
    SELECT encode(substring(int4send(shard) FROM 3 FOR 2) || '\x010000000000'::bytea || substring(v7 FROM 1 FOR 6) || substring(v7 FROM 11 FOR 2), 'hex')::uuid
    FROM (SELECT uuid_send(uuidv7()) AS v7) AS s;
$$;

-- a read-only record (ro, system, deleted or archived: Linked Data, # Flags) changes only its flags, and is never deleted;
-- `archived` comes with the status `abandoned`, `deleted` with the status `rejected`
CREATE FUNCTION ld.record()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.flags & 23 <> 0 THEN
            RAISE EXCEPTION '%.% % is read only (flags %): it is not deleted', TG_TABLE_SCHEMA, TG_TABLE_NAME, OLD.id, OLD.flags;
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.flags & 23 <> 0 AND to_jsonb(NEW) - 'flags' - 'updated' - 'status' - 'kind' - 'ts' IS DISTINCT FROM to_jsonb(OLD) - 'flags' - 'updated' - 'status' - 'kind' - 'ts' THEN
            RAISE EXCEPTION '%.% % is read only (flags %): only its flags change', TG_TABLE_SCHEMA, TG_TABLE_NAME, OLD.id, OLD.flags;
        END IF;
        NEW.updated := now();
    END IF;
    IF NEW.meta->>'status' IS DISTINCT FROM OLD.meta->>'status' THEN
        NEW.flags := NEW.flags | CASE NEW.meta->>'status' WHEN 'abandoned' THEN 16 WHEN 'rejected' THEN 4 ELSE 0 END;
    END IF;
    RETURN NEW;
END;
$$;

-- a schema's types: a row adds `slug` and `shard`, the table its records are in (its `stored_as`), and the types table's own for a type
-- with no records of its own; a value's `kind` is the type its vocabulary applies to. A slug is one under its parent.
CREATE TABLE ld.types (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'0000'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    slug      text NOT NULL,
    shard     integer NOT NULL,
    UNIQUE NULLS NOT DISTINCT (parent_id, slug)
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON ld.types FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE ld.nodes (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'0001'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON ld.nodes FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE ld.links (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'0010'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    from_id   uuid,
    to_id     uuid
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON ld.links FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE ld.events (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'0020'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON ld.events FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE fs.types (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'1000'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    slug      text NOT NULL,
    shard     integer NOT NULL,
    UNIQUE NULLS NOT DISTINCT (parent_id, slug)
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON fs.types FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE fs.locations (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'1001'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON fs.locations FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE fs.files (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'1002'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON fs.files FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE fs.instances (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'1003'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON fs.instances FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE fs.links (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'1010'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    from_id   uuid,
    to_id     uuid
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON fs.links FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE sessions.types (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'2000'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    slug      text NOT NULL,
    shard     integer NOT NULL,
    UNIQUE NULLS NOT DISTINCT (parent_id, slug)
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON sessions.types FOR EACH ROW EXECUTE FUNCTION ld.record();

-- a session is known by its harness and the id its harness gives it
CREATE TABLE sessions.sessions (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'2001'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE UNIQUE INDEX sessions_harness_uid ON sessions.sessions ((meta->>'harness'), (meta->>'uid'));
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON sessions.sessions FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE sessions.messages (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'2002'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz
);
CREATE INDEX ON sessions.messages (parent_id);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON sessions.messages FOR EACH ROW EXECUTE FUNCTION ld.record();

CREATE TABLE sessions.links (
    id        uuid PRIMARY KEY DEFAULT ld.uuid_create(x'2010'::int),
    flags     smallint NOT NULL DEFAULT 0,
    type      text,
    status    text GENERATED ALWAYS AS (meta->>'status') STORED,
    kind      text GENERATED ALWAYS AS (meta->>'kind') STORED,
    parent_id uuid,
    span      tstzrange,
    ts        timestamptz GENERATED ALWAYS AS (lower(span)) STORED,
    data      jsonb NOT NULL DEFAULT '{}',
    meta      jsonb NOT NULL DEFAULT '{}',
    created   timestamptz NOT NULL DEFAULT now(),
    updated   timestamptz,
    from_id   uuid,
    to_id     uuid
);
CREATE TRIGGER record BEFORE INSERT OR UPDATE OR DELETE ON sessions.links FOR EACH ROW EXECUTE FUNCTION ld.record();

-- a row of the types table of the schema its shard's first byte names (# UUID): its name, kind and uri in `meta`, its parent the
-- row of that slug in any schema's types; an id the store makes has two random bytes in its millisecond, so one already taken is
-- made again
CREATE PROCEDURE ld.type_create(slug text, shard int, name text, parent text DEFAULT NULL, kind text DEFAULT NULL, uri text DEFAULT NULL, data jsonb DEFAULT '{}')
LANGUAGE plpgsql
AS $$
DECLARE
    taken text;
BEGIN
    LOOP
        BEGIN
            EXECUTE format('INSERT INTO %I.types (slug, shard, parent_id, data, meta) VALUES ($1, $2, $3, $4, $5)',
                           CASE shard >> 8 WHEN x'00'::int THEN 'ld' WHEN x'10'::int THEN 'fs' WHEN x'20'::int THEN 'sessions' END)
            USING type_create.slug, type_create.shard,
                  (SELECT t.id FROM (SELECT l.id, l.slug FROM ld.types l UNION ALL SELECT f.id, f.slug FROM fs.types f UNION ALL SELECT s.id, s.slug FROM sessions.types s) t
                   WHERE t.slug = type_create.parent),
                  type_create.data, jsonb_strip_nulls(jsonb_build_object('display_name', type_create.name, 'kind', type_create.kind, 'uri', type_create.uri));
            RETURN;
        EXCEPTION WHEN unique_violation THEN
            GET STACKED DIAGNOSTICS taken = CONSTRAINT_NAME;
            IF taken <> 'types_pkey' THEN
                RAISE;
            END IF;
        END;
    END LOOP;
END;
$$;

-- the type rows, written by ld_types.py from the Turtle: change the Turtle, not these lines
CALL ld.type_create(slug => 'meta', shard => x'0000'::int, name => 'Metadata', uri => 'uo:Metadata');
CALL ld.type_create(slug => 'record', shard => x'0000'::int, name => 'Record', uri => 'uo:Record');
CALL ld.type_create(slug => 'type', shard => x'0000'::int, name => 'Type', parent => 'record', uri => 'uo:Type');
CALL ld.type_create(slug => 'cv', shard => x'0000'::int, name => 'Controlled Vocabulary', parent => 'type', uri => 'uo:ControlledVocabulary');
CALL ld.type_create(slug => 'dimension', shard => x'0000'::int, name => 'Dimension', parent => 'cv', uri => 'uo:Dimension');
CALL ld.type_create(slug => 'axis', shard => x'0000'::int, name => 'Axis', parent => 'dimension', uri => 'uo:Axis');
CALL ld.type_create(slug => 'label', shard => x'0000'::int, name => 'Label', parent => 'cv', uri => 'uo:Label');
CALL ld.type_create(slug => 'kind', shard => x'0000'::int, name => 'Kind', parent => 'label', uri => 'uo:Kind');
CALL ld.type_create(slug => 'assistant', shard => x'2000'::int, name => 'Assistant', parent => 'kind', kind => 'message', uri => 'uo:SessionMessageAssistant');
CALL ld.type_create(slug => 'chore', shard => x'0000'::int, name => 'Chore', parent => 'kind', kind => 'work', uri => 'uo:WorkChore');
CALL ld.type_create(slug => 'class', shard => x'0000'::int, name => 'Class', parent => 'kind', kind => 'knowledge', uri => 'uo:KnowledgeClass');
CALL ld.type_create(slug => 'comment', shard => x'0000'::int, name => 'Comment', parent => 'kind', kind => 'knowledge', uri => 'uo:KnowledgeComment');
CALL ld.type_create(slug => 'concept', shard => x'0000'::int, name => 'Concept', parent => 'kind', kind => 'knowledge', uri => 'uo:KnowledgeConcept');
CALL ld.type_create(slug => 'developer', shard => x'2000'::int, name => 'Developer', parent => 'kind', kind => 'message', uri => 'uo:SessionMessageDeveloper');
CALL ld.type_create(slug => 'document', shard => x'0000'::int, name => 'Document', parent => 'kind', kind => 'knowledge', uri => 'uo:KnowledgeDocument');
CALL ld.type_create(slug => 'experiment', shard => x'0000'::int, name => 'Experiment', parent => 'kind', kind => 'work', uri => 'uo:WorkExperiment');
CALL ld.type_create(slug => 'feature', shard => x'0000'::int, name => 'Feature', parent => 'kind', kind => 'work', uri => 'uo:WorkFeature');
CALL ld.type_create(slug => 'graph', shard => x'0000'::int, name => 'Graph', parent => 'kind', kind => 'knowledge', uri => 'uo:KnowledgeGraph');
CALL ld.type_create(slug => 'junction', shard => x'1000'::int, name => 'Junction', parent => 'kind', kind => 'instance', uri => 'uo:InstanceJunction');
CALL ld.type_create(slug => 'lecture', shard => x'0000'::int, name => 'Lecture', parent => 'kind', kind => 'knowledge', uri => 'uo:KnowledgeLecture');
CALL ld.type_create(slug => 'mention', shard => x'0000'::int, name => 'Mention', parent => 'kind', kind => 'knowledge', uri => 'uo:KnowledgeMention');
CALL ld.type_create(slug => 'offline', shard => x'1000'::int, name => 'Offline', parent => 'kind', kind => 'instance', uri => 'uo:InstanceOffline');
CALL ld.type_create(slug => 'ongoing', shard => x'0000'::int, name => 'Ongoing', parent => 'kind', kind => 'work', uri => 'uo:WorkOngoing');
CALL ld.type_create(slug => 'problem', shard => x'0000'::int, name => 'Problem', parent => 'kind', kind => 'work', uri => 'uo:WorkProblem');
CALL ld.type_create(slug => 'route', shard => x'0000'::int, name => 'Route', parent => 'kind', kind => 'knowledge', uri => 'uo:KnowledgeRoute');
CALL ld.type_create(slug => 'script', shard => x'0000'::int, name => 'Script', parent => 'kind', kind => 'knowledge', uri => 'uo:KnowledgeScript');
CALL ld.type_create(slug => 'symlink', shard => x'1000'::int, name => 'Symlink', parent => 'kind', kind => 'instance', uri => 'uo:InstanceSymlink');
CALL ld.type_create(slug => 'table', shard => x'0000'::int, name => 'Table', parent => 'kind', kind => 'knowledge', uri => 'uo:KnowledgeTable');
CALL ld.type_create(slug => 'term', shard => x'0000'::int, name => 'Term', parent => 'kind', kind => 'knowledge', uri => 'uo:KnowledgeTerm');
CALL ld.type_create(slug => 'thinking', shard => x'2000'::int, name => 'Thinking', parent => 'kind', kind => 'message', uri => 'uo:SessionMessageThinking');
CALL ld.type_create(slug => 'tool_result', shard => x'2000'::int, name => 'Tool result', parent => 'kind', kind => 'message', uri => 'uo:SessionMessageToolResult');
CALL ld.type_create(slug => 'tool_use', shard => x'2000'::int, name => 'Tool use', parent => 'kind', kind => 'message', uri => 'uo:SessionMessageToolUse');
CALL ld.type_create(slug => 'user', shard => x'2000'::int, name => 'User', parent => 'kind', kind => 'message', uri => 'uo:SessionMessageUser');
CALL ld.type_create(slug => 'theme', shard => x'0000'::int, name => 'Theme', parent => 'label', uri => 'uo:Theme');
CALL ld.type_create(slug => 'status', shard => x'0000'::int, name => 'Status', parent => 'cv', uri => 'uo:Status');
CALL ld.type_create(slug => 'abandoned', shard => x'0000'::int, name => 'Abandoned', parent => 'status', kind => 'work', uri => 'uo:StatusAbandoned');
CALL ld.type_create(slug => 'active', shard => x'0000'::int, name => 'Active', parent => 'status', kind => 'record', uri => 'uo:StatusActive');
CALL ld.type_create(slug => 'completed', shard => x'0000'::int, name => 'Completed', parent => 'status', kind => 'activity', uri => 'uo:StatusCompleted');
CALL ld.type_create(slug => 'parsed', shard => x'1000'::int, name => 'Parsed', parent => 'status', kind => 'file', uri => 'uo:StatusParsed');
CALL ld.type_create(slug => 'pending', shard => x'0000'::int, name => 'Pending', parent => 'status', kind => 'work', uri => 'uo:StatusPending');
CALL ld.type_create(slug => 'planned', shard => x'0000'::int, name => 'Planned', parent => 'status', kind => 'work', uri => 'uo:StatusPlanned');
CALL ld.type_create(slug => 'proposed', shard => x'0000'::int, name => 'Proposed', parent => 'status', kind => 'record', uri => 'uo:StatusProposed');
CALL ld.type_create(slug => 'rejected', shard => x'0000'::int, name => 'Rejected', parent => 'status', kind => 'record', uri => 'uo:StatusRejected');
CALL ld.type_create(slug => 'suspended', shard => x'0000'::int, name => 'Suspended', parent => 'status', kind => 'work', uri => 'uo:StatusSuspended');
CALL ld.type_create(slug => 'harness', shard => x'2000'::int, name => 'Harness', parent => 'cv', uri => 'uo:Harness');
CALL ld.type_create(slug => 'agy', shard => x'2000'::int, name => 'Antigravity', parent => 'harness', kind => 'session', uri => 'uo:HarnessAntigravity');
CALL ld.type_create(slug => 'cc', shard => x'2000'::int, name => 'Claude Code', parent => 'harness', kind => 'session', uri => 'uo:HarnessClaudeCode');
CALL ld.type_create(slug => 'copilot', shard => x'2000'::int, name => 'Copilot', parent => 'harness', kind => 'session', uri => 'uo:HarnessCopilot');
CALL ld.type_create(slug => 'cx', shard => x'2000'::int, name => 'Codex', parent => 'harness', kind => 'session', uri => 'uo:HarnessCodex');
CALL ld.type_create(slug => 'gemini', shard => x'2000'::int, name => 'Gemini', parent => 'harness', kind => 'session', uri => 'uo:HarnessGemini');
CALL ld.type_create(slug => 'hermes', shard => x'2000'::int, name => 'Hermes', parent => 'harness', kind => 'session', uri => 'uo:HarnessHermes');
CALL ld.type_create(slug => 'openclaw', shard => x'2000'::int, name => 'OpenClaw', parent => 'harness', kind => 'session', uri => 'uo:HarnessOpenClaw');
CALL ld.type_create(slug => 'openviking', shard => x'2000'::int, name => 'OpenViking', parent => 'harness', kind => 'session', uri => 'uo:HarnessOpenViking');
CALL ld.type_create(slug => 'ov', shard => x'0000'::int, name => 'Open Vocabulary', parent => 'type', uri => 'uo:OpenVocabulary');
CALL ld.type_create(slug => 'tag', shard => x'0000'::int, name => 'Tag', parent => 'ov', uri => 'uo:Tag');
CALL ld.type_create(slug => 'node', shard => x'0001'::int, name => 'Node', parent => 'record', uri => 'uo:Node');
CALL ld.type_create(slug => 'entity', shard => x'0001'::int, name => 'Entity', parent => 'node', uri => 'uo:Entity');
CALL ld.type_create(slug => 'knowledge', shard => x'0001'::int, name => 'Knowledge', parent => 'node', uri => 'uo:Knowledge');
CALL ld.type_create(slug => 'event', shard => x'0020'::int, name => 'Event', parent => 'node', uri => 'uo:Event');
CALL ld.type_create(slug => 'activity', shard => x'0020'::int, name => 'Activity', parent => 'event', uri => 'uo:Activity');
CALL ld.type_create(slug => 'work', shard => x'0000'::int, name => 'Work', parent => 'activity', uri => 'uo:Work');
CALL ld.type_create(slug => 'epic', shard => x'0001'::int, name => 'Epic', parent => 'work', uri => 'uo:Epic');
CALL ld.type_create(slug => 'project', shard => x'0001'::int, name => 'Project', parent => 'work', uri => 'uo:Project');
CALL ld.type_create(slug => 'task', shard => x'0001'::int, name => 'Task', parent => 'work', uri => 'uo:Task');
CALL ld.type_create(slug => 'session', shard => x'2001'::int, name => 'Session', parent => 'activity', uri => 'uo:Session');
CALL ld.type_create(slug => 'link', shard => x'0010'::int, name => 'Link', parent => 'record', uri => 'uo:Link');
CALL ld.type_create(slug => 'prov-o', shard => x'0000'::int, name => 'PROV-O', parent => 'link', uri => 'http://www.w3.org/ns/prov#');
CALL ld.type_create(slug => 'influenced-by', shard => x'0010'::int, name => 'InfluencedBy', parent => 'prov-o', uri => 'prov:wasInfluencedBy');
CALL ld.type_create(slug => 'associated-with', shard => x'0010'::int, name => 'AssociatedWith', parent => 'influenced-by', uri => 'prov:wasAssociatedWith');
CALL ld.type_create(slug => 'attributed-to', shard => x'0010'::int, name => 'AttributedTo', parent => 'influenced-by', uri => 'prov:wasAttributedTo');
CALL ld.type_create(slug => 'derived-from', shard => x'0010'::int, name => 'DerivedFrom', parent => 'influenced-by', uri => 'prov:wasDerivedFrom');
CALL ld.type_create(slug => 'ended-by', shard => x'0010'::int, name => 'EndedBy', parent => 'influenced-by', uri => 'prov:wasEndedBy');
CALL ld.type_create(slug => 'generated-by', shard => x'0010'::int, name => 'GeneratedBy', parent => 'influenced-by', uri => 'prov:wasGeneratedBy');
CALL ld.type_create(slug => 'informed-by', shard => x'0010'::int, name => 'InformedBy', parent => 'influenced-by', uri => 'prov:wasInformedBy');
CALL ld.type_create(slug => 'invalidated-by', shard => x'0010'::int, name => 'InvalidatedBy', parent => 'influenced-by', uri => 'prov:wasInvalidatedBy');
CALL ld.type_create(slug => 'started-by', shard => x'0010'::int, name => 'StartedBy', parent => 'influenced-by', uri => 'prov:wasStartedBy');
CALL ld.type_create(slug => 'down', shard => x'0010'::int, name => 'Down', parent => 'link', uri => 'uo:Down');
CALL ld.type_create(slug => 'next', shard => x'0010'::int, name => 'Next', parent => 'link', uri => 'uo:Next');
CALL ld.type_create(slug => 'prev', shard => x'0010'::int, name => 'Prev', parent => 'link', uri => 'uo:Prev');
CALL ld.type_create(slug => 'related', shard => x'0010'::int, name => 'Related', parent => 'link', uri => 'uo:Related');
CALL ld.type_create(slug => 'same', shard => x'0010'::int, name => 'Same', parent => 'link', uri => 'skos:exactMatch');
CALL ld.type_create(slug => 'up', shard => x'0010'::int, name => 'Up', parent => 'link', uri => 'uo:Up');
CALL ld.type_create(slug => 'location', shard => x'1001'::int, name => 'Location', uri => 'uo:Location');
CALL ld.type_create(slug => 'host', shard => x'1001'::int, name => 'Host', parent => 'location', uri => 'uo:Host');
CALL ld.type_create(slug => 'file', shard => x'1002'::int, name => 'File', uri => 'uo:File');
CALL ld.type_create(slug => 'archive', shard => x'1002'::int, name => 'Archive', parent => 'file', uri => 'uo:Archive');
CALL ld.type_create(slug => 'csv', shard => x'1002'::int, name => 'CSV', parent => 'file', uri => 'uo:CSV');
CALL ld.type_create(slug => 'email', shard => x'1002'::int, name => 'Email', parent => 'file', uri => 'uo:Email');
CALL ld.type_create(slug => 'export', shard => x'1002'::int, name => 'Export', parent => 'file', uri => 'uo:Export');
CALL ld.type_create(slug => 'folder', shard => x'1002'::int, name => 'Folder', parent => 'file', uri => 'uo:Folder');
CALL ld.type_create(slug => 'projects', shard => x'1002'::int, name => 'Projects', parent => 'folder', uri => 'uo:Projects');
CALL ld.type_create(slug => 'sessionfolder', shard => x'1002'::int, name => 'Session folder', parent => 'folder', uri => 'uo:SessionFolder');
CALL ld.type_create(slug => 'work-folder', shard => x'1002'::int, name => 'Work folder', parent => 'folder', uri => 'uo:WorkFolder');
CALL ld.type_create(slug => 'log', shard => x'1002'::int, name => 'Log', parent => 'file', uri => 'uo:Log');
CALL ld.type_create(slug => 'markdown', shard => x'1002'::int, name => 'Markdown', parent => 'file', uri => 'uo:Markdown');
CALL ld.type_create(slug => 'session-file', shard => x'1002'::int, name => 'Session file', parent => 'file', uri => 'uo:SessionFile');
CALL ld.type_create(slug => 'sqlite', shard => x'1002'::int, name => 'SQLite', parent => 'file', uri => 'uo:SQLite');
CALL ld.type_create(slug => 'instance', shard => x'1003'::int, name => 'Instance', uri => 'uo:Instance');
CALL ld.type_create(slug => 'message', shard => x'2002'::int, name => 'Message', uri => 'uo:SessionMessage');
CALL ld.type_create(slug => 'kind', shard => x'0000'::int, name => 'Kind', parent => 'meta', uri => 'uo:kind');
CALL ld.type_create(slug => 'status', shard => x'0000'::int, name => 'Status', parent => 'meta', uri => 'uo:status');
CALL ld.type_create(slug => 'tags', shard => x'0000'::int, name => 'Tags', parent => 'meta', uri => 'uo:tags');
CALL ld.type_create(slug => 'uri', shard => x'0000'::int, name => 'uri', parent => 'meta', uri => 'uo:URI');
CALL ld.type_create(slug => 'axis', shard => x'0000'::int, name => 'Axis', parent => 'meta', kind => 'work', uri => 'uo:hasAxis');
CALL ld.type_create(slug => 'theme', shard => x'0000'::int, name => 'Theme', parent => 'meta', kind => 'work', uri => 'uo:hasTheme');
-- the end of the type rows
