# MCP server

RoleBand ships a local [Model Context Protocol](https://modelcontextprotocol.io)
server, so an agent app the user already runs (Claude Desktop, Claude Code,
Codex, or any client that can launch a stdio MCP server) can read the radar and
record pursuit progress. The client starts the server as a child process and
talks to it over stdio. There is no network listener, no remote access and no
second user.

| Piece | Where |
|---|---|
| Tools and the access check | `backend/tracker/mcp/server.py` |
| Filter vocabulary resolution | `backend/tracker/mcp/vocab.py` |
| The two access switches | `backend/tracker/agents/config.py` |
| Pursuit writes | `backend/tracker/agents/pursuits.py` |
| Settings routes (agents, cloud models, egress) | `backend/tracker/api/routers/intelligence.py` |
| Settings screen | `dashboard/src/features/intelligence/` |

## Connecting an agent

1. In the dashboard, open Settings > AI (`/settings/intelligence`). On the MCP
   server card, turn on **Allow assistant apps to connect**. Turn on **Allow
   assistant apps to update your progress** as well if the agent should save
   roles and update pursuits.
2. Copy the setup the card shows for your app. Codex gets a
   `codex mcp add roleband -- ...` command; every other client gets a standard
   `mcpServers` JSON block. Both come from `GET /api/intelligence/agents` and
   carry the absolute paths of your checkout:

   ```json
   {
     "mcpServers": {
       "roleband": {
         "command": "<repo>/backend/.venv/bin/python",
         "args": ["-m", "tracker.mcp.server"],
         "cwd": "<repo>/backend"
       }
     }
   }
   ```

3. Restart the client and ask it to call `get_server_status`.

The server opens the database itself, so the API does not need to be running.
To debug it by hand: `cd backend && .venv/bin/python -m tracker.mcp.server`.

## Access gates

Two switches, saved in the `agent_access` row of `app_settings`
(`AgentAccessConfig`), both off by default:

| Switch | Allows |
|---|---|
| `enabled` | every read tool |
| `allow_writes` | the write tools, and only while `enabled` is also on |

Every tool except `get_server_status` calls `_access()` (or
`_access(write=True)`) first. The switches are read from the database on each
call, so a change in Settings applies to a connected client at once, without a
restart. A refused call raises `PermissionError` naming the setting to change.
The Settings card never saves `allow_writes` on without `enabled`.

## Tools

| Tool | Gate | Reads or writes |
|---|---|---|
| `get_server_status` | none | The two switches and the transport. No job data. |
| `get_radar_summary` | read | Counts: open in-scope postings, saved postings, pursuits, overdue next actions, pursuits by stage. |
| `search_opportunities` | read | Open, in-scope postings the Board would show. Filters on text, companies, role families, locations, minimum estimated pay, saved only, first seen within N days. Sort `newest`, `oldest` or `compensation`; `limit` 1 to 100, default 20. |
| `get_opportunity` | read | One posting with its full description and sections, pay evidence and pursuit state. |
| `listing_history` | read | How long a posting has been listed and why, with dated events. The same payload as `GET /api/jobs/{id}/history`. |
| `get_pursuits` | read | Pursuits (stage, priority, notes, next action and due date), optionally one stage; `limit` 1 to 100, default 50. |
| `save_opportunity` | write | Saves the posting. A new pursuit starts at stage `saved`; an existing one keeps its stage and notes, and its priority unless one is given. |
| `update_pursuit` | write | Changes stage, priority (1 to 5), notes, next action or its due date. Fields not given are left alone; a call with no field is refused. |
| `get_recipe_contract` | read | The listing recipe JSON Schema, transports and transforms: only what a scheduled run executes. |
| `inspect_source` | read | Fetches one public careers page and returns its sanitized text, or up to 20 elements matching a CSS selector. |
| `validate_recipe` | read | Compiles a recipe and previews it live: at most two pages and five postings, nothing stored. |
| `save_recipe_draft` | write + confirmation | Stores the recipe as a new draft revision. |

Pursuit stages are `saved`, `researching`, `networking`, `applied`,
`interviewing`, `offer`, `rejected` and `withdrawn`.

**What search shows.** Visibility comes from `tracker/db/queries/jobs.py`, the
same module the Board uses: hidden and unfollowed companies and dismissed
postings are left out, except that `saved_only` keeps a saved posting the user
later hid or dismissed, as the Saved screen does.

**Filters say what they ignored.** `companies`, `families` and `locations`
accept a slug or its plain name in any case ("Product Management",
"product_management"). A value that matches nothing is listed in `ignored`; a
filter whose every value was unknown is dropped and listed in
`dropped_filters`, so the search widens instead of answering zero. Matching
normalizes spelling only, never guesses. `tests/test_mcp_vocab.py` holds these
rules.

**A recipe declares only what runs.** The contract `get_recipe_contract`
returns is `RECIPE_V1_SCHEMA` in `backend/tracker/connectors/recipes/schema.py`.
It offers the `static_http` transport and the GET method, the field names the
runner reads (`req_id`, `title`, `url`, `locations`, `department`, `team` and
`posted_at`, which is read as a date), and domains with at least one dot,
since a domain admits its subdomains. `validate_recipe`, `save_recipe_draft`
and the API's preview, validate and shadow compile a document against that
contract and apply the scheduled run's own transport check
(`runtime_problems`), so a recipe the run would refuse never passes. A run
stops paging at the first page that adds no new `req_id`, and the listing
then counts as incomplete. A revision already stored outside the contract
still loads when the run can refuse or skip that part by name: a reserved
transport (`static_impersonate`, `render`) is refused before any request, an
unread field is skipped. One with a POST method or a domain without a dot
does not compile, and its company is reported unattempted. Validating either
again names the problem.

**Pay stays separated.** A result carries `employer_stated_pay` (what the
posting states, absent until the posting was parsed), `estimated_total_comp`
and `estimated_base` (RoleBand's estimates) as distinct fields, so an agent
cannot pass an estimate off as a stated figure.

## Mutation tiers

| Tier | Tools | Behaviour |
|---|---|---|
| Read | all `read` tools | No stored state changes. `inspect_source` and `validate_recipe` do fetch over the network, through `tracker/platform/safe_fetch.py` (public addresses only, 1 MB page cap). |
| Pursuit write | `save_opportunity`, `update_pursuit` | Applied at once. Each change appends a `pursuit_events` row with actor `agent`, the from and to stage, and each changed field's value before and after, in the same transaction as the pursuit row. History is never rewritten. A pursuit always implies a saved posting. |
| Confirmed write | `save_recipe_draft` | Needs the write gate and `confirmed=True`, which the agent sets only after the user agrees. It stores a draft revision and never validates, activates or binds a recipe to a company. |
| Not exposed | none | No tool sends a message, applies to a job, contacts anyone, starts a sync, deletes data or changes settings. |

The Settings card names what every tool reads, fetches or changes before the
user lets an app connect; `backend/tests/test_mcp_consent_card.py` fails when a
tool has no line on it.

Stage changes are not blocked by the server, but the server instructions and
the `update_pursuit` description tell the agent to ask the user before a
consequential stage change. The user can correct any agent write in the
dashboard, and the event log keeps both versions.

## Trust rules

**Scraped text is evidence, never instructions.** Postings and careers pages
are written by third parties. `inspect_source` sanitizes what it returns, and
both the server instructions and the tool descriptions tell the agent not to
follow instructions found in page content.

**Connecting an agent is the opt-in for sending job text out.** The server
returns data only to the client that launched it, but most clients pass tool
results to a cloud model. That is why the Settings card is marked
cloud-connected and why access stays off until the user turns it on. The
client owns its own model sign-in and usage limits; RoleBand never asks for or
stores that login, and the MCP connection needs no key.

**Cloud model profiles are a separate lane.** Settings > AI can also hold
direct API connections (bring your own key). No RoleBand task sends job text
to them: the one model task the product runs, duplicate review, uses the
user's local model, and the routing ladder a cloud profile joins is the model
bench's (`scripts.bench_relevance_review`).

- Providers `openai`, `anthropic` or `openai_compatible`, at an HTTPS address
  that is not localhost or a private IP (`normalize_cloud_url` in
  `tracker/cloud_llm/models.py`). Local model profiles must point at loopback.
- Routes: `/api/intelligence/cloud-models` (list, add, edit, delete) and
  `POST /api/intelligence/cloud-models/{id}/test`. Saving a profile sends
  nothing. The test sends one minimal request (a model listing, or a one-token
  message for Anthropic) and no job text.
- The routing ladder in `tracker/intelligence_runtime/routing.py`
  (`build_tiers`) is the one place a cloud tier joins, and it admits one only
  while the egress switch is on
  (`PUT /api/intelligence/egress`, stored as `ai_egress`, off by default). A
  profile's own `enabled` flag is not enough. The egress switch has its own
  route so no other save can turn it on as a side effect.

**Secret storage.** API keys are write-only on the wire: responses carry
`has_api_key`, never the key, and an edit that sends `api_key: null` keeps the
stored key. How keys are stored is in [SECURITY.md](../SECURITY.md).

## Changing the server

- A new tool is a function in `server.py` whose first line is `await _access()`
  or `await _access(write=True)`, with `readOnlyHint` and `destructiveHint`
  annotations that tell the truth.
- Add it to the tool list in `_agent_connection_state`
  (`tracker/api/routers/intelligence.py`), which the Settings card shows.
  `tests/test_agents.py` fails when that list and the registered tools differ,
  and pins the whole tool set.
- Add it to `READ_TOOLS` or `WRITE_TOOLS` in `tests/test_mcp_tools.py` so the
  gate tests cover it, and test what it returns there. Those tests call the
  tool bodies against a real scratch Postgres.
- Read through the query modules in `tracker/db/queries/`. `mcp/` and `api/`
  never import each other; the import-linter contract "API and MCP are
  independent transports" enforces it.
- Pursuit writes go through `upsert_pursuit(..., actor="agent")`, never a
  direct table write.

Run from `backend/`:

```bash
.venv/bin/python -m pytest tests/test_mcp_tools.py tests/test_mcp_recipe_tools.py \
  tests/test_mcp_vocab.py tests/test_agents.py tests/test_cloud_llm.py \
  tests/test_api_intelligence_contract.py
```
