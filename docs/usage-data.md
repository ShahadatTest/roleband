# What RoleBand shares when you choose to share

Sharing is optional. Nothing is sent unless you turn it on, on the question RoleBand asks once
(first launch, or once for an install set up before sharing existed) or in Settings › Privacy.
You can turn each kind off at any time; what was waiting to be sent for it is then never sent.
A batch whose send is already in progress can finish.

This page lists everything that can leave your computer. `tests/test_usage_docs.py` holds it
equal to the code (`backend/tracker/usage_stats/registry.py`), in both directions: an event or a
property the code can send and this page does not list fails the build, and so does one listed
here that the code does not send.

## Where it goes

- **PostHog Cloud, EU region** (`eu.i.posthog.com`). RoleBand's project discards client IP
  addresses and runs no IP location lookup. Data is never sold.
- **Under a random install ID**: a UUID made the first time you share anything, linked to
  nothing else (no account, name, email, machine or user name). It links one install's events
  together, which is what shows whether people keep using a feature. Settings › Privacy shows it,
  and **Reset ID** replaces it: nothing new is then linked to what was sent before.
- **Never included**: company names, role titles, compensation, your CV or profile, anything you type,
  URLs with ids in them, error messages from the backend, file paths, your user or host name.
- **No session recordings**: RoleBand never records your screen or how you move through it.

## Turning it off

- Settings › Privacy: one switch per kind.
- For a whole machine, any of these environment variables (also read from `backend/.env`, which
  the background agents use): `ROLEBAND_NO_USAGE_STATS=1`, `DO_NOT_TRACK=1`, or `CI` set. Each
  turns everything off whatever was chosen; none can turn anything on.
- **Deleting what was sent**: email your install ID (Settings › Privacy) to
  security@roleband.com and we delete its events and person profile in PostHog. Send it before
  you press **Reset ID**: a reset replaces the ID and keeps no copy of the old one.

## The kinds of sharing

### Anonymous usage data (`usage`)

From the dashboard, through PostHog's browser library, while this kind is on:

- `pageviews`
- `pageleave`
- `autocapture`
- `heatmaps`
- `dead_clicks`
- `rage_clicks`
- `web_vitals`
- `person_profile`
- `feature_flags`
- `experiments`
- `early_access`

Screen addresses are reduced to the screen (`/jobs/:id`, never the job's id); text that comes
from employers or from you (company names, titles, pay, your profile, notes, search) is masked
and never captured with a click.

From the backend, once a day:

### `daily_heartbeat`

| Property | Values |
|---|---|
| `app_version` | the release, e.g. `0.1.0` |
| `os` | `macos`, `linux`, `windows`, `other` |
| `os_major` | the OS major version, a number |
| `arch` | `arm64`, `x86_64`, `other` |
| `python` | e.g. `3.12` |
| `install_method` | `source`, `package`, `container` |
| `db_mode` | `embedded`, `external` |
| `followed_bucket` | how many companies you follow: `0`, `1-5`, `6-20`, `21-50`, `51-100`, `101+` |
| `ai_egress` | whether job text may go to a cloud AI model you configured |
| `ui_locale` | the dashboard's language, e.g. `en` |
| `country` | the two-letter region of your OS settings (never your IP) |
| `target_craft` | the kind of role you look for, as one of RoleBand's role families (`software_engineering`, `product_management`, ...), or `several`, or `any`; never your own words |
| `target_seniority` | the level you aim for: `intern`, `entry`, `mid`, `senior`, `staff`, `principal`, `director_plus` |

### `daily_action`

| Property | Values |
|---|---|
| `action` | which kind of change you made, one name per kind (`save_job`, `follow_all`, `settings_saved`, ...), counted per day; never which job or company |

### `daily_scan_health`

| Property | Values |
|---|---|
| `family` | the job-site family scanned (`greenhouse`, `lever`, `ashby`, `smartrecruiters`, `workable`, `workday`); a company's own careers site, or a family fewer than 10 known employers use, is `single_company` |
| `outcome` | how the scan ended (`ok`, `failed`, `blocked`, ...) |

### `daily_ai_task`

| Property | Values |
|---|---|
| `task` | which AI task ran (a code name) |
| `provider` | which kind of model ran it |
| `outcome` | how it ended |
| `failure` | why it failed, as a code name |
| `model` | the vendor's model id, for cloud models only; a local model's name is never sent |
| `latency_p50_ms` | the day's median time, in milliseconds |
| `input_tokens` | the day's total input tokens |
| `output_tokens` | the day's total output tokens |

No prompt and no model output: the local AI log never stores them.

### `first_company_followed`

Once, the first time after you share.

### `first_job_saved`

Once, the first time after you share.

### `first_scan_finished`

| Property | Values |
|---|---|
| `outcome` | how that first scan ended |

### Crash reports (`crashes`)

From the dashboard, through PostHog's browser library:

- `exceptions`

Error messages are cleaned of addresses, emails, quoted text and long numbers before they leave.

From the backend:

### `$exception`

| Property | Values |
|---|---|
| `source` | `api`, `pipeline` or `scheduler` |

With the exception's type and the places in RoleBand's own code it passed through (module,
function, line). No message, no file path, no variable. A place in code written for one employer
(a company's own careers-site connector) is reported as `single_company`.

### Feedback surveys (`questions`)

From the dashboard, through PostHog's browser library:

- `surveys`

Now and then a short question. What you answer is what you chose to write.

## The collection ledger

Each kind is reviewed on its date and retired once it no longer pays for itself. Retiring
something never asks you again; adding something to a kind asks again for that kind only.

| Kind | Since | Review | Retired when |
|---|---|---|---|
| Anonymous usage data | at release | 6 months after release | the main screens are settled |
| Crash reports | at release | yearly | never planned |
| Feedback surveys | at release | yearly | never planned |
