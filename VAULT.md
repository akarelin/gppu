# Vault: fix yaml registration, add designation handling, correct AGENTS.md compliance gaps

## Context

Reading `~/RAN/AGENTS.md` after the recent Vault refactor surfaced four gaps that need closing as one coherent change:

1. **`Vault.yaml_register()` is the wrong layer.** `dict_from_yml` in `gppu/gppu.py:251` registers every other yaml hook (`!include`, defaultdict/UserDict/set/tuple representers) by calling `yaml.add_constructor` / `yaml.add_representer` inline. The `!secret` constructor is the only one wrapped in a method on `Vault`. That indirection isn't earning anything — it should be one more inline `yaml.add_constructor` call alongside the others, and the `Vault.yaml_register` static method should be deleted.

2. **No designation handling in Vault.** AGENTS.md `Keys and tokens` defines a secret-naming convention: secret name = consumer env-var name in kebab-case-lower; a designation suffix `<env-var-kebab>-<designation>` is appended only when a base-name collision exists; the designation must be sourced from an existing context identifier (tenant id, workspace id, project id, scope id), never invented; and the user is asked only when there is both a collision and no context identifier to draw from. The current `Vault` passes names through verbatim — no env-var-to-kebab conversion, no collision-with-designation logic, no helper at all. Existing patterns like `neo4j-{server}-uri` and `msgraph-*` are hardcoded by their consumers, not produced by a shared helper.

3. **Earlier plan documented forbidden deploy step.** A prior revision said `cd /home/alex/A/mcp && docker compose up -d --build`. AGENTS.md `Infrastructure` is explicit: "Docker Compose: deploy only via portainer.karel.in" and "Do not restart services, Docker, or Docker Compose." Plan needs to point at the Portainer flow; `mcp/README.md` `## Run` section needs the same correction.

4. **Earlier plan ignored venv discipline.** Steps like `pip install -e /home/alex/gppu` were written without specifying a venv. AGENTS.md `Python Environment`: default venv is at the repo root, activated before any `pip`/`python`; nothing into system Python or user-site.

Intended outcome: clean yaml registration, a `Vault.name_for(env_var, **context)` helper that implements the designation rule, and a verification/deploy section that respects AGENTS.md.

## A. Inline the `!secret` yaml constructor

**File:** `/home/alex/gppu/gppu/gppu.py`
No lambdas. Create yml_secret exacly like yml_include
Around line 249–251, replace:
```python
yaml.add_constructor("!include", yml_include, Loader=yaml.FullLoader)


**Delete** the `Vault.yaml_register` static method (the four-line `@staticmethod def yaml_register():` block near the bottom of the Vault class). No external callers.

**File:** `/home/alex/gppu/tests/test_vault.py`

The autouse `_clean` fixture calls `Vault.yaml_register()`. Replace with an `import yaml` at the top of the test file plus, inside the fixture, `yaml.add_constructor("!secret", lambda l, n: Vault.get(n.value), Loader=yaml.FullLoader)`.

## B. Designation support on Vault

**Rule restated:** secret name = `kebab-lower(env_var)`; on collision, append `-<designation>` sourced from a context identifier; never invent. Caller-side prompting for an unsupplied designation is out of Vault's scope — Vault raises and the caller (MCP tool / skill / script) handles the prompt.

**File:** `/home/alex/gppu/gppu/gppu.py`, inside `class Vault` (next to `get` / `create` / `update`):

```python
_DESIGNATION_KEYS = ('tenant_id', 'workspace_id', 'project_id', 'scope_id')

@staticmethod
def name_for(env_var: str, **context: str) -> str:
  """Canonical vault secret name for an env-var, per AGENTS.md.

  Returns kebab-lower(env_var). On collision, appends '-<designation>' sourced from
  context keys in priority order: tenant_id, workspace_id, project_id, scope_id, then
  any remaining string-valued kwarg in insertion order. Raises ValueError if there is
  a collision and no context identifier is available — caller must prompt the user.
  """
  base = env_var.lower().replace('_', '-')
  if not Vault._exists(base):
    return base
  # Collision — pick a designation from context
  keys = [k for k in Vault._DESIGNATION_KEYS if k in context]
  keys += [k for k in context if k not in Vault._DESIGNATION_KEYS]
  for k in keys:
    v = context[k]
    if not v:
      continue
    suffix = str(v).lower().replace('_', '-')
    candidate = f"{base}-{suffix}"
    if not Vault._exists(candidate):
      return candidate
  raise ValueError(
    f"Secret name '{base}' already exists and no available context identifier "
    f"(checked {list(context.keys()) or 'none'}) yields a free designated name. "
    f"Caller must supply a designation explicitly.")
```

**Note:** `name_for` does not write — it only resolves a name. Callers do:
```python
secret_name = Vault.name_for("SLACK_BOT_TOKEN", workspace_id="T012ABC")
Vault.create(secret_name, token_value)
```

**MCP tool:** add a fifth tool to `/home/alex/A/mcp/tools_keys.py`:
```python
{"name": "secret_name_for",
 "description": "Resolve the canonical vault secret name from an env-var + context. Returns the name (with designation suffix on collision). Does not write.",
 "inputSchema": {
   "type": "object",
   "properties": {
     "env_var": {"type": "string", "description": "Consumer env-var name (any case; will be converted to kebab-lower)"},
     "context": {"type": "object", "description": "Context identifiers (tenant_id / workspace_id / project_id / scope_id / etc.)", "additionalProperties": {"type": "string"}}},
   "required": ["env_var"]},
 "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}
```
Handler:
```python
"secret_name_for": lambda a: {"name": Vault.name_for(a["env_var"], **(a.get("context") or {}))},
```

`mcp/README.md` `/keys` table grows to 5 tools.

**Skill doc** (`/home/alex/A/plugins/core/skills/core/SKILL.md` Secrets section): add a one-liner explaining the designation convention and pointing callers to `secret_name_for` before `secret_create`. Reference AGENTS.md `Keys and tokens`.

**Tests** (`/home/alex/gppu/tests/test_vault.py`): add a `TestNameFor` class covering: no-collision returns base; collision + tenant_id appends; collision priority order (tenant before workspace before project before scope); collision + no usable context raises; collision + designated-name-also-collides falls through to next key.

## C. Deploy via Portainer, not docker compose

Real deploy chain for `mcp.karelin.ai`:

1. gppu source change → push to `git@github.com:akarelin/gppu.git` → `gh workflow run gppu.yml -R akarelin/gppu -f bump=patch -f beta=false -f run_tests=true` → wait for release; capture new wheel URL.
2. Bump `mcp/requirements.txt:5` to the new wheel URL; apply call-site edits; push to `git@github.com:akarelin/AGENTS.md.git`; `gh workflow run "MCP Build" -R akarelin/AGENTS.md` → image lands at `ghcr.io/akarelin/mcp:latest`.
3. **Portainer redeploy:** trigger via `https://portainer.karel.in` API using the Portainer API key from the karelin vault. Exact stack id / endpoint id needs user input — bake into `mcp/README.md` once known. **No `docker compose` commands, no SSH-and-restart.**
4. Reconnect MCP clients (claude.ai connector, Claude Code) so the new tool list (`secret_get`, `secret_list`, `secret_create`, `secret_update`, `secret_name_for`) is fetched.

**File:** `/home/alex/A/mcp/README.md` `## Run` section — currently says `docker compose up -d --build`. Replace with the Portainer flow above.

## D. Venv discipline in any local install/test step

All `pip`/`python` invocations in this plan run *inside the relevant venv*:
- gppu dev: `source /home/alex/gppu/venv/bin/activate` before `pip install -e .`
- A repo (if Python work is needed there): `source /home/alex/A/venv/bin/activate` before `pip install ...`
- Pytest: from the same activated venv.

Exact venv paths to be verified (`ls /home/alex/gppu/venv/ /home/alex/A/venv/`) before any install runs.

## E. Skill-file location — not migrated

The Secrets skill content is at `/home/alex/A/plugins/core/skills/core/SKILL.md`. This matches the Claude Code plugin spec layout (`<plugin-root>/skills/<skill-name>/SKILL.md`, with `<plugin-root>/.claude-plugin/plugin.json`), which is what the `akarelin/A` marketplace repo's `plugins/README.md` already advertises. AGENTS.md's reference to `~/A/skills` predates the plugin marketplace and is stale. **No migration in this plan.** Open a follow-up to update AGENTS.md's `Skills and plugins` section to point at the plugin-spec layout if desired.

## Files modified

- `/home/alex/gppu/gppu/gppu.py` — Section A (inline `!secret` constructor, drop `Vault.yaml_register`); Section B (`Vault.name_for` + `_DESIGNATION_KEYS`)
- `/home/alex/gppu/tests/test_vault.py` — Section A (fixture rework); Section B (new `TestNameFor`)
- `/home/alex/A/mcp/tools_keys.py` — Section B (`secret_name_for` tool + handler)
- `/home/alex/A/mcp/README.md` — Section B (`/keys` table grows to 5); Section C (`## Run` switches to Portainer)
- `/home/alex/A/plugins/core/skills/core/SKILL.md` — Section B (mention designation + `secret_name_for`)

## Verification

After Section A edits:
```bash
source /home/alex/gppu/venv/bin/activate
python -c "from gppu import Vault; assert not hasattr(Vault, 'yaml_register'); print('A: yaml_register removed')"
pytest /home/alex/gppu/tests/test_vault.py::TestYamlIntegration -x
```

After Section B edits:
```bash
pytest /home/alex/gppu/tests/test_vault.py::TestNameFor -x
python -c "
import sys; sys.path.insert(0,'/home/alex/A/mcp'); import tools_keys
assert [t['name'] for t in tools_keys.TOOLS] == ['secret_get','secret_list','secret_create','secret_update','secret_name_for']
"
```

After Section C edit:
```bash
grep -q "docker compose" /home/alex/A/mcp/README.md && echo 'STILL PRESENT — fix' || echo 'C: docker-compose mention removed'
grep -q "portainer.karel.in" /home/alex/A/mcp/README.md && echo 'C: portainer flow documented'
```

End-to-end (post-deploy, against the live MCP): `secret_name_for(env_var="TEST_ENV_VAR")` returns `"test-env-var"`; `secret_name_for(env_var="TEST_ENV_VAR", context={"tenant_id":"T01"})` returns `"test-env-var"` if free, else `"test-env-var-t01"`.

## Out of scope

- Migrating skill files between `~/A/plugins/...` and `~/A/skills/...` (Section E — no change).
- Updating `~/RAN/AGENTS.md` to reflect the Claude Code plugin spec (follow-up).
- Actually triggering the Portainer redeploy — Section C documents the procedure; execution is a separate confirmed step that needs the stack id from the user.
- Adding designation-aware tooling to existing call sites (`graph_client.py`, `tools_neo4j.py`, `tt.py`, `google_client.py`) — they currently work with hardcoded names; migrating them to `Vault.name_for` is a follow-up if/when those services gain multi-credential support.
