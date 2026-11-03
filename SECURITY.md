# Security

## Reporting a vulnerability

Report it privately through GitHub's **Report a vulnerability** button on this
repository's Security tab, or by email to security@roleband.com. Please do not open
a public issue. Include what you found, how to reproduce it, and what an attacker
could do with it. We acknowledge reports within a few days and tell you when a fix
ships.

## The security model

RoleBand is a single-user application that runs on your own computer.

- The API and the dashboard listen on the loopback interface only
  (`127.0.0.1:8010` when installed with `deploy/install.sh`). There is no
  authentication: anyone who can reach that port can use the app. Do not expose it
  to a network.
- Data lives in an embedded Postgres under your user's home directory. Keys you
  enter (a cloud or local model key, a price-data key) are stored in that database
  encrypted, with a key kept in `~/.roleband/secret.key` (readable by you only, and
  never in `data/` or a backup). A backup therefore holds those keys only as
  ciphertext: to restore one on another computer, copy that file too, or enter the
  keys again. Anyone who can read your files can read both, so this protects copies
  of the database, not a compromised account
  ([saved keys](docs/architecture.md#data-model-and-persistence)).
  `deploy/backup_db.sh` also makes backup files readable only by the account that
  made them.
- The dashboard is served with a Content-Security-Policy
  (`backend/tracker/api/csp.py`): it loads scripts only from the app itself.
- The local MCP server (`docs/mcp.md`) runs over standard input and output for an
  agent you start yourself; its read and write access are separate switches, both off
  until you turn them on.
- The Mac app installs an update only when its release files are signed with one
  of the app's two release keys and the new app meets the signing rule the installed
  app carries. A candidate that fails is discarded. The app sends the person to a
  release page to install by hand only when the candidate carries a valid Apple
  Developer ID signature, so a stolen release key used with a self-made certificate
  never leads anyone to install by hand. A failed update restores the previous app
  and database ([Mac app updates](docs/architecture.md#mac-app-updates)). A
  "Before you update" notice is shown only from a release's signed metadata;
  the same heading in the unsigned release notes shows as ordinary notes
  ([release signing](docs/architecture.md#release-signing-and-keys)).

## Checking a Mac release

The Mac app is signed with RoleBand's own code-signing certificate, and its release
files with a release key. Their public halves:

| | Value |
|---|---|
| Signing certificate, SHA-256 | `b5a722badd7dbbc933f981dd5c23b0a6611f667096d09240c63d7d7f52d3049d` |
| Release key (Ed25519) | `yE/8O/lAN2omr3Ko8yAZbsiOrhk3oQpNd+T9dRyaOAk=` |
| Spare release key (Ed25519) | `/hHA2GHjlXsuoPpMkQBy5zRI/qDLjmuWk5HCKPD/BaI=` |

The app checks every update against these keys itself. To check a copy you got
another way, run these in Terminal with its path (for a disk image, open it and use
the app inside):

```bash
codesign --verify --deep --strict /Applications/RoleBand.app
codesign -d --extract-certificates=/tmp/roleband-cert /Applications/RoleBand.app
shasum -a 256 /tmp/roleband-cert0
plutil -extract RoleBandUpdatePublicKey raw /Applications/RoleBand.app/Contents/Info.plist
plutil -extract RoleBandUpdateSpareKey raw /Applications/RoleBand.app/Contents/Info.plist
```

The first prints nothing when the signature holds. The digest and the two keys must
equal the table; any other value means the app is not RoleBand's.

## What leaves your computer

| What | When | Controlled in |
|---|---|---|
| Requests to job boards and company career sites | When a company you follow is synced. Each source's route, the User-Agent sent and how the request is made are listed in `docs/sources.md`. A site whose `robots.txt` disallows that route is read only for a company you agreed to in a dialog, and only then with a browser's headers or TLS fingerprint where its row says so. | `backend/tracker/source_policy.py` |
| A careers URL you paste | When you add a company by URL, and on every later scan of the board that page named; public addresses only, and only on that board's own host. | `backend/tracker/platform/safe_fetch.py` |
| Embedding model weights | Once, during setup or the Mac app's first open; pinned and checked against a sha256 per file. | `backend/tracker/semantic/provision.py` |
| A check of a cloud model service you configure | Only when you press its Test button, after you turn on AI egress (`ai_egress_enabled`, off by default) and add your own key: one minimal request, no job text. No RoleBand task sends job text to a cloud model. Local OpenAI-compatible servers on your own machine stay local. | `backend/tracker/api/routers/intelligence.py` |
| A search query sent for parsing | Only after you turn on AI egress, and only with `search_llm_enabled` and an API key; off by default. | `backend/tracker/search/llm.py` |
| Requests for daily stock prices | Only if you add a price-data key. | `backend/tracker/prices/provider.py` |
| Plugin requests | Only from plugins you approved, only to the hosts their manifest declares. | `backend/tracker/plugins/host.py` |
| Pages an AI agent asks for | Only with agent access on, when an agent calls `inspect_source` or `validate_recipe`; public addresses only. | `docs/mcp.md` |
| Anonymous usage events | Only if you opt in; exactly what is sent is listed in `docs/usage-data.md`. | `backend/tracker/usage_stats/` |
| A Mac app's update check: the release listing at `api.github.com/repos/roleband/roleband/releases/latest`, then the newest release's checksum, metadata and signature (no disk image) from that release on `github.com` and GitHub's asset host `release-assets.githubusercontent.com` | Once a day when automatic checks are on, or when the user selects Check now. GitHub receives the network address and a generic launcher User-Agent; no RoleBand postings, settings, credentials or personal data are sent. A release is offered only when its metadata verifies with one of the installed app's two release keys, the current one or its spare; a check installs nothing. Release notes show as text, and opening a release page in the browser is a separate explicit action. | Launcher preferences; `launcher/macos/Sources/LauncherCore/Updates.swift` |
| A Mac app update's disk image | Only after the user selects Update, from the same two hosts. Requests carry no credentials or cookies, and only HTTPS URLs for the selected release are accepted. The image's signed size and SHA256 must match before it is installed, under the update rule above. | `launcher/macos/Sources/LauncherCore/UpdateDownload.swift` |

Anything not in this table is a defect: please report it as above.
