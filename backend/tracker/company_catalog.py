"""Catalog of known companies a user can add from Settings.

Code-as-data (mirrors `config.COMPANIES`), and vocabulary like it: it imports
nothing, so the source register and the collection policy can read which
provider a catalog company is declared on (`source_review.declared_adapter`).
Every entry names its adapter and the board token we know for it, so adding
one needs no discovery step. The built-in companies in `config.COMPANIES` are
intentionally NOT duplicated here.

An entry is an OFFER, not a roster row: it makes `connector_state` report
`ready`, and nothing is fetched until a user adds the company. Adding rows is
therefore a data change, not a capacity change: the nightly roster does not
move by one request.

`board_region` is optional and means what it means on `TrackedCompany`: the
regional deployment of a multi-region ATS, ABSENT when the family has a single
host. Lever is the only such family here, and the key is not defaulted: "this
family has one deployment" and "this tenant is on the global host" are
different records, and a wrong region answers the same 404 as a wrong token, so
it can never be recovered from a failure.

**Board tokens rot, and a wrong one is not a safe failure.** A dead board
answers 404, not an empty board: the read is `failed` (`outcome.board_missing`)
on every scan and the company collects nothing until the token is fixed. A
token that resolves to another company's live board is worse, because no run
gate can tell. Re-check with `python -m scripts.check_catalog_tokens`, by hand,
on the same monthly cadence as `check_vendored_upstream`, since tests never
touch the live network. A token added here without running it is a guess.

**`curated` is a separate question from "ready".** A row with `"curated": True`
is on the curated list (the companies a user starts with and the ones "Include
other companies" does not touch); an absent key means it is not
(`company_discovery.is_curated`). A ready connector is an offer, never a
default follow.
"""

from __future__ import annotations

# slug -> {display, adapter, board_token[, board_region][, curated]}
CATALOG: dict[str, dict] = {
    # --- Greenhouse boards (boards-api.greenhouse.io/v1/boards/{token}) ------
    "stripe": {"curated": True, "display": "Stripe", "adapter": "greenhouse", "board_token": "stripe"},
    "databricks": {"display": "Databricks", "adapter": "greenhouse", "board_token": "databricks"},
    "airbnb": {"curated": True, "display": "Airbnb", "adapter": "greenhouse", "board_token": "airbnb"},
    "coinbase": {"display": "Coinbase", "adapter": "greenhouse", "board_token": "coinbase"},
    # Vercel's Ashby board still answers `{"jobs": []}`, which reads as
    # "not hiring", while Greenhouse `vercel` names "Vercel" and lists its
    # postings. An empty board can be a moved one.
    "vercel": {"display": "Vercel", "adapter": "greenhouse", "board_token": "vercel"},
    # `doordash` 404s; the live board is `doordashusa`.
    "doordash": {"curated": True, "display": "DoorDash", "adapter": "greenhouse", "board_token": "doordashusa"},
    "dropbox": {"display": "Dropbox", "adapter": "greenhouse", "board_token": "dropbox"},
    "pinterest": {"display": "Pinterest", "adapter": "greenhouse", "board_token": "pinterest"},
    "reddit": {"display": "Reddit", "adapter": "greenhouse", "board_token": "reddit"},
    "lyft": {"curated": True, "display": "Lyft", "adapter": "greenhouse", "board_token": "lyft"},
    "gitlab": {"curated": True, "display": "GitLab", "adapter": "greenhouse", "board_token": "gitlab"},
    "figma": {"display": "Figma", "adapter": "greenhouse", "board_token": "figma"},
    "discord": {"display": "Discord", "adapter": "greenhouse", "board_token": "discord"},
    "brex": {"display": "Brex", "adapter": "greenhouse", "board_token": "brex"},
    "affirm": {"display": "Affirm", "adapter": "greenhouse", "board_token": "affirm"},
    "samsara": {"display": "Samsara", "adapter": "greenhouse", "board_token": "samsara"},
    "instacart": {"display": "Instacart", "adapter": "greenhouse", "board_token": "instacart"},
    "robinhood": {"display": "Robinhood", "adapter": "greenhouse", "board_token": "robinhood"},
    "asana": {"display": "Asana", "adapter": "greenhouse", "board_token": "asana"},
    "twitch": {"display": "Twitch", "adapter": "greenhouse", "board_token": "twitch"},
    "gusto": {"display": "Gusto", "adapter": "greenhouse", "board_token": "gusto"},
    "flexport": {"display": "Flexport", "adapter": "greenhouse", "board_token": "flexport"},
    "scaleai": {"display": "Scale AI", "adapter": "greenhouse", "board_token": "scaleai"},
    # The board root declares "Datadog", `/jobs` returns the whole board in one
    # response, and every apply URL resolves to `careers.datadoghq.com`, the
    # official careers domain in `company_discovery`: the board is linked to the
    # careers site by the employer's own configuration rather than by a name
    # that merely matches.
    "datadog": {"curated": True, "display": "Datadog", "adapter": "greenhouse", "board_token": "datadog"},
    # Each token below was resolved from the employer's own board, and
    # `check_catalog_tokens` confirms it. Greenhouse states its tenant, so every
    # Greenhouse row is identity CONFIRMED and not merely live.
    "xai": {"curated": True, "display": "SpaceXAI", "adapter": "greenhouse", "board_token": "xai"},
    "nintendo": {"curated": True, "display": "Nintendo", "adapter": "greenhouse", "board_token": "nintendo"},
    "epic-games": {"display": "Epic Games", "adapter": "greenhouse", "board_token": "epicgames"},
    "riot-games": {"display": "Riot Games", "adapter": "greenhouse", "board_token": "riotgames"},
    "roblox": {"display": "Roblox", "adapter": "greenhouse", "board_token": "roblox"},
    "take-two-interactive": {"display": "Take-Two Interactive", "adapter": "greenhouse", "board_token": "taketwo"},
    "block": {"curated": True, "display": "Block", "adapter": "greenhouse", "board_token": "block"},
    # Ashby-style capitalization on a Greenhouse board: `adyen` 404s, `Adyen`
    # serves the board. The token is the tenant's own string, never a slug.
    "adyen": {"curated": True, "display": "Adyen", "adapter": "greenhouse", "board_token": "Adyen"},
    "jane-street": {"curated": True, "display": "Jane Street", "adapter": "greenhouse", "board_token": "janestreet"},
    # The quant desks name their boards after the firm, not the domain:
    # hudson-river-trading is `wehrtyou`, optiver `optiverus`, drw `drweng`,
    # xtx-markets `xtxmarketstechnologies`. Guessing the slug 404s on all four.
    "hudson-river-trading": {"curated": True, "display": "Hudson River Trading", "adapter": "greenhouse", "board_token": "wehrtyou"},
    # Not curated: a sector's curated list holds its first three eligible
    # companies, and Two Sigma, earlier in the quant order, holds the third.
    "optiver": {"display": "Optiver", "adapter": "greenhouse", "board_token": "optiverus"},
    # Board declares "IMC" where our display is "IMC Trading"; the declared
    # alias is what settles the identity probe (see `check_catalog_tokens`).
    # The EU tenant is on Greenhouse's single API host, so no region applies.
    "imc-trading": {"display": "IMC Trading", "adapter": "greenhouse", "board_token": "imc"},
    "jump-trading": {"display": "Jump Trading", "adapter": "greenhouse", "board_token": "jumptrading"},
    "drw": {"display": "DRW", "adapter": "greenhouse", "board_token": "drweng"},
    "tower-research-capital": {"display": "Tower Research Capital", "adapter": "greenhouse", "board_token": "towerresearchcapital"},
    "xtx-markets": {"display": "XTX Markets", "adapter": "greenhouse", "board_token": "xtxmarketstechnologies"},
    "zscaler": {"curated": True, "display": "Zscaler", "adapter": "greenhouse", "board_token": "zscaler"},
    "okta": {"curated": True, "display": "Okta", "adapter": "greenhouse", "board_token": "okta"},
    "wiz": {"display": "Wiz", "adapter": "greenhouse", "board_token": "wizinc"},
    "sentinelone": {"display": "SentinelOne", "adapter": "greenhouse", "board_token": "sentinellabs"},
    "mongodb": {"display": "MongoDB", "adapter": "greenhouse", "board_token": "mongodb"},
    "elastic": {"display": "Elastic", "adapter": "greenhouse", "board_token": "elastic"},
    "grafana-labs": {"display": "Grafana Labs", "adapter": "greenhouse", "board_token": "grafanalabs"},
    "waymo": {"curated": True, "display": "Waymo", "adapter": "greenhouse", "board_token": "waymo"},
    "nuro": {"display": "Nuro", "adapter": "greenhouse", "board_token": "nuro"},
    "zipline": {"display": "Zipline", "adapter": "greenhouse", "board_token": "flyzipline"},
    "rocket-lab": {"display": "Rocket Lab", "adapter": "greenhouse", "board_token": "rocketlab"},
    # Greenhouse `figure` is a live, complete, perfectly healthy board belonging
    # to **Figure Lending** — a different company from figure.ai. It is the
    # wrong-company case, recorded as a token in
    # `tests/test_catalog_tokens.py` rather than as a slug, because the hazard
    # is the token and any slug could carry it back. figure.ai's own board is
    # `figureai`: the root declares "Figure", every location is a place, and
    # apply URLs are on job-boards.greenhouse.io, so the careers-domain measure
    # is not obtained.
    "figure": {"display": "Figure", "adapter": "greenhouse", "board_token": "figureai"},
    # The board declares "Cloudflare". `location.name` is a work arrangement
    # (Hybrid/Distributed/In-Office), not a place: the places are in `offices`,
    # which the adapter reads, and the arrangement becomes `workplace_type`.
    # Some postings state only a region label ("AMER", "EMEA"), which by design
    # never matches a location group directly. Apply URLs are on
    # boards.greenhouse.io, so the careers-domain measure is not obtained.
    # Curated as one of its sector's first three eligible companies.
    "cloudflare": {"curated": True, "display": "Cloudflare", "adapter": "greenhouse", "board_token": "cloudflare"},
    # Found by `scripts.discover_board_tokens` as name PREFIXES, which equality
    # cannot reach. anduril: the board declares "Anduril Industries" (an alias);
    # a few postings say only "Remote". playstation: the board declares
    # "PlayStation Global" (an alias). Apply URLs are on boards.greenhouse.io
    # and job-boards.greenhouse.io respectively, so the careers-domain measure
    # is not obtained for either. Both are curated as one of their sector's
    # first three eligible companies.
    "anduril": {"curated": True, "display": "Anduril", "adapter": "greenhouse", "board_token": "andurilindustries"},
    "playstation": {"curated": True, "display": "PlayStation", "adapter": "greenhouse",
                    "board_token": "sonyinteractiveentertainmentglobal"},
    # --- Ashby boards (api.ashbyhq.com/posting-api/job-board/{name}) ---------
    "notion": {"display": "Notion", "adapter": "ashby", "board_token": "Notion"},
    "ramp": {"display": "Ramp", "adapter": "ashby", "board_token": "Ramp"},
    "linear": {"display": "Linear", "adapter": "ashby", "board_token": "Linear"},
    # `perplexity-ai` 404s; `Perplexity` is the live board. Ashby board names
    # are the tenant's own capitalization, which is why guessed lowercase slugs
    # miss.
    "perplexity": {"display": "Perplexity", "adapter": "ashby", "board_token": "Perplexity"},
    # Runway AI's board is `runway-ml`, the one runway.com/careers links
    # (runwayml.com redirects there). `runwayml` 404s, and `Runway` is a
    # business-planning company's board: live, complete and somebody else's,
    # which no run gate catches.
    "runway": {"display": "Runway", "adapter": "ashby", "board_token": "runway-ml"},
    "cohere": {"display": "Cohere", "adapter": "ashby", "board_token": "cohere"},
    # Board name is the bare tenant `ami`, not the domain slug. `amilabs` 404s.
    "ami-labs": {"display": "AMI Labs", "adapter": "ashby", "board_token": "ami"},
    # lovable.dev/careers is a rendered shell whose every posting link points at
    # jobs.ashbyhq.com/lovable: the board name is the plain domain slug here.
    "lovable": {"display": "Lovable", "adapter": "ashby", "board_token": "lovable"},
    # The tenant is the full domain, dot included: `mistral`, `mistralai` and
    # `mistral-ai` all 404. Every posting link on mistral.ai/careers points at
    # jobs.ashbyhq.com/mistral.ai. Removing a dead entry does not help the users
    # who already added it, which is why `check_catalog_tokens` probes tokens in
    # use, not just these.
    "mistral": {"display": "Mistral AI", "adapter": "ashby", "board_token": "mistral.ai"},
    # Ashby names no tenant on its API, so these are LIVE and identity
    # `unstated`: onboarding is the human check, and the monthly probe catches a
    # token that dies.
    "snowflake": {"display": "Snowflake", "adapter": "ashby", "board_token": "snowflake"},
    "supercell": {"display": "Supercell", "adapter": "ashby", "board_token": "supercell"},
    "plaid": {"display": "Plaid", "adapter": "ashby", "board_token": "plaid"},
    "1password": {"display": "1Password", "adapter": "ashby", "board_token": "1password"},
    "confluent": {"display": "Confluent", "adapter": "ashby", "board_token": "confluent"},
    "docker": {"display": "Docker", "adapter": "ashby", "board_token": "docker"},
    "skydio": {"display": "Skydio", "adapter": "ashby", "board_token": "skydio"},
    # The legal entity, not the product: `aurora` 404s.
    "aurora": {"display": "Aurora", "adapter": "ashby", "board_token": "aurora-operations-inc"},
    # --- Workable boards (apply.workable.com/api/v1/widget/accounts/{token}) -
    # The account payload declares "Hugging Face"; one request returns the
    # whole board with every description inline; the apply URLs resolve to
    # `apply.workable.com/j/{shortcode}`, the provider's own host rather than a
    # tenant custom domain, so that measure is unavailable here and identity
    # carries the link; `locations` are PLACES (city, region and country stated
    # separately), never a work arrangement.
    "hugging-face": {"display": "Hugging Face", "adapter": "workable", "board_token": "huggingface"},
    # Eightfold PCSX tenants. Their v2 API answers 403 "Not authorized for
    # PCSX", hence the `|pcsx` suffix. Identity is `unstated` (Eightfold names
    # no tenant on any route we read); locations are PLACES ("London, County
    # London, England, United Kingdom").
    "paypal": {"display": "PayPal", "adapter": "eightfold",
               "board_token": "paypal.eightfold.ai|paypal.com|pcsx"},
    "qualcomm": {"curated": True, "display": "Qualcomm", "adapter": "eightfold",
                 "board_token": "careers.qualcomm.com|qualcomm.com|pcsx"},
    # Micron: the family names no tenant (identity `unstated`); every URL is on
    # careers.micron.com; robots allows `/api/pcsx`. One full sweep fits the
    # source's time ceiling; only a run needing two recovery sweeps is bounded.
    "micron": {"display": "Micron", "adapter": "eightfold",
               "board_token": "careers.micron.com|micron.com|pcsx"},
    # BCG's experienced board, not talent.bcg.com (student-only listing).
    # Locations are places; identity is unstated by the API. The official
    # careers page links experiencedtalent.bcg.com. API canonical URLs also use
    # the student host, which serves the same posting id/title; both apply via
    # BCG login.
    "boston-consulting-group": {"curated": True, "display": "Boston Consulting Group",
                                "adapter": "eightfold", "board_token": "experiencedtalent.bcg.com|bcg.com"},
    # Deel job boards, token = the org slug on jobs.deel.com. The per-org
    # sitemap is the board (the page's list comes from the robots-disallowed
    # /api/). `location` values are PLACES from the posting JSON-LD ("Sweden",
    # "Stockholm, Sweden"); the board names no tenant (identity `unstated`);
    # URLs are jobs.deel.com, linked from klarna.com/careers.
    "klarna": {"display": "Klarna", "adapter": "deel", "board_token": "klarna"},
    # Radancy TalentBrew, token = the tenant's careers host. The sitemap is the
    # board; robots disallows only the search. `location` values are PLACES
    # built from locality/region/country ("Austin, Texas, United States"); the
    # site names no tenant on the sitemap (identity `unstated`); URLs are
    # careers.arm.com.
    "arm": {"curated": True, "display": "Arm", "adapter": "radancy", "board_token": "careers.arm.com"},
    # Workday tenants, token `host|site`. This source is USER-DIRECTED: every
    # row here is disabled by default, is followed one company at a time, and
    # is scanned only by a sync the user starts. The catalog offering it is not
    # the app collecting it. Each tenant's CXS route (POST) answers with its
    # declared `total` and real postings. `location` values are PLACES, in each
    # tenant's own phrasing ("San Jose", "Wilton, CT, USA", "India - Remote").
    # The route states no tenant name, so identity is `unstated`, and the
    # checker cannot verify these tokens at all: it probes with GET and the CXS
    # route answers 400.
    "salesforce": {"display": "Salesforce", "adapter": "workday",
                   "board_token": "salesforce.wd12.myworkdayjobs.com|External_Career_Site"},
    "adobe": {"display": "Adobe", "adapter": "workday",
              "board_token": "adobe.wd5.myworkdayjobs.com|external_experienced"},
    "unity": {"display": "Unity", "adapter": "workday",
              "board_token": "unitytech.wd1.myworkdayjobs.com|Unity"},
    "crowdstrike": {"display": "CrowdStrike", "adapter": "workday",
                    "board_token": "crowdstrike.wd5.myworkdayjobs.com|crowdstrikecareers"},
    "palo-alto-networks": {"display": "Palo Alto Networks", "adapter": "workday",
                           "board_token": "paloaltonetworks.wd5.myworkdayjobs.com|panwexternalcareers"},
    "snyk": {"display": "Snyk", "adapter": "workday",
             "board_token": "snyk.wd103.myworkdayjobs.com|External"},
    "intel": {"display": "Intel", "adapter": "workday",
              "board_token": "intel.wd1.myworkdayjobs.com|External"},
    "broadcom": {"display": "Broadcom", "adapter": "workday",
                 "board_token": "broadcom.wd1.myworkdayjobs.com|External_Career"},
    "asml": {"display": "ASML", "adapter": "workday",
             "board_token": "asml.wd3.myworkdayjobs.com|ASMLEXT1"},
    # 2,000 is the CXS soft ceiling, not this board's size: the adapter's facet
    # subdivision is what reads past it.
    "applied-materials": {"display": "Applied Materials", "adapter": "workday",
                          "board_token": "amat.wd1.myworkdayjobs.com|External"},
    "cadence": {"display": "Cadence", "adapter": "workday",
                "board_token": "cadence.wd1.myworkdayjobs.com|External_Careers"},
    # snap's board is on Workday's SHARED host, which names no tenant, so the
    # token does. Many rows list "N Locations" and are placed from their
    # detail; the board names no tenant (identity unstated); postings sit on
    # wd1.myworkdaysite.com, which careers.snap.com links to.
    "snap": {"display": "Snap", "adapter": "workday", "board_token": "wd1.myworkdaysite.com|snap|snapchat"},
    # PwC US experienced careers. Detail places read like "TX-Dallas" and
    # "NY-New York". Identity is unstated by CXS; official PwC postings link
    # this tenant. Apply URLs stay on pwc.wd3.myworkdayjobs.com. User-directed,
    # uncurated.
    "pwc": {"display": "PwC", "adapter": "workday",
            "board_token": "pwc.wd3.myworkdayjobs.com|US_Experienced_Careers"},
    # Jibe career sites, token = the tenant's careers host. The listing states
    # `totalCount`; `location` values are PLACES (GitHub's are mostly a country:
    # "United States", remote roles); the board names the employer
    # (`hiring_organization`: "GitHub, Inc."; Booking's carries both
    # "Booking.com" and its parent "Booking Holdings", both kept); URLs are the
    # tenant careers host.
    "github": {"curated": True, "display": "GitHub", "adapter": "jibe", "board_token": "www.github.careers"},
    "booking": {"display": "Booking.com", "adapter": "jibe", "board_token": "jobs.booking.com"},
    # Both name their employer, publish places and descriptions inline, and
    # keep posting URLs on their official careers hosts. Robots allows / with
    # crawl-delay 5, already enforced by Jibe's per-tenant pacer.
    "amd": {"curated": True, "display": "AMD", "adapter": "jibe", "board_token": "careers.amd.com"},
    "susquehanna-international-group": {"display": "Susquehanna International Group",
                                        "adapter": "jibe", "board_token": "careers.sig.com"},
    # Avature portals, token `host|portal`. `location` values are PLACES
    # ("Vancouver, Canada", the detail's fuller "Hyderabad, Telangana, India");
    # the portal names no tenant (identity `unstated`); URLs are jobs.ea.com.
    # No posted date is published.
    "electronic-arts": {"display": "Electronic Arts", "adapter": "avature", "board_token": "jobs.ea.com|en_US/careers"},
    # Synopsys: careers.synopsys.com is Radancy TalentBrew, whose robots
    # disallows `/search-jobs/`; its postings apply through this Avature portal,
    # whose robots allows `/careers`. `location` values are PLACES (the
    # detail's City + Country: "Shanghai, China"); the portal names no tenant
    # (identity `unstated`); URLs are synopsys.avature.net.
    "synopsys": {"display": "Synopsys", "adapter": "avature", "board_token": "synopsys.avature.net|careers"},
    # TSMC, on the WALLED route: careers.tsmc.com answers identified clients
    # with a Cloudflare challenge, so it is collected on the TLS tier, only
    # after a user follows it and consents; never curated. `location` values
    # are PLACES ("Taiwan", "USA-Arizona", "Japan-Kumamoto"); the detail names
    # the company ("Taiwan Semiconductor Manufacturing Company Limited"); URLs
    # are careers.tsmc.com. Robots allows `/*/careers`.
    "tsmc": {"display": "TSMC", "adapter": "avature_tls", "board_token": "careers.tsmc.com|en_US/careers"},
    # Deloitte US: the `|capped` Avature shape. `data-total="999+"` is a
    # display cap (paging reads past 999 to an empty page), so the walk is
    # uncounted, over pages that overlap by one row. Cards state
    # `Deloitte US | <legal entity> | <place>`; "Multiple Locations" is placed
    # from the posting page's locations block, or from places read within
    # `description_refresh_days` (`known_places`). Robots allows `/careers` and
    # `/*/careers` except `qtvc=`. The posting names "Deloitte US" (JSON-LD
    # hiringOrganization); URLs are apply.deloitte.com. Not curated: Bain,
    # earlier in the consulting order, holds the third slot.
    "deloitte": {"display": "Deloitte", "adapter": "avature",
                 "board_token": "apply.deloitte.com|en_US/careers|capped"},
    # Bain & Company: the `|folder` Avature shape on careers.bain.com (tenant
    # bain.avature.net; not Bain Capital, a separate Workday employer). Walked
    # newest first by the portal's posted-date column: the default order repeats
    # a posting across a page boundary and skips another. Robots allows `/jobs`
    # except `qtvc=`. `location` values are PLACES, cities comma-joined per card
    # and split; the page names "Bain & Company, Inc." but the probe reads no
    # identity, so `unstated`; URLs are careers.bain.com.
    "bain-company": {"curated": True, "display": "Bain & Company", "adapter": "avature",
                     "board_token": "careers.bain.com|jobs|folder"},
    # Two Sigma: the `|openroles` portal shape, declared in the token.
    # SearchJobs answers 404; OpenRoles lists 10 a page and states NO total, so
    # the listing ends on its empty page (uncounted closure; the careers
    # sitemap names no postings). Robots allows `/careers` except `qtvc=`.
    # `location` values are PLACES ("United States - NY New York", "United
    # Kingdom - UK London", "Japan -  Tokyo"); the portal names no tenant
    # (identity `unstated`); URLs are careers.twosigma.com.
    "two-sigma": {"curated": True, "display": "Two Sigma", "adapter": "avature",
                  "board_token": "careers.twosigma.com|careers|openroles"},
    # Accenture's own careers search API, not the Pinpoint tenant (graduate
    # postings only). Read per country query against `totalHits`; a country
    # past the search's 10,000 window is left out. `location` values are
    # PLACES ("New York City, NY"); the API names no tenant (identity
    # `unstated`); URLs are accenture.com job pages.
    "accenture": {"curated": True, "display": "Accenture", "adapter": "accenture", "board_token": "accenture"},
    # KPMG US's own careers search, not SuccessFactors. A card is a job at a
    # place, so one job can fill several cards; every card id is seen once
    # against the stated count. `location` values are PLACES ("New York, NY");
    # the JSON-LD names "KPMG LLP" but the search does not, so identity is
    # `unstated`; apply URLs are kpmguscareers.com. The token names nothing:
    # the route is fixed. Not curated: a company earlier in the consulting
    # order holds the third slot.
    "kpmg": {"display": "KPMG", "adapter": "kpmg", "board_token": "kpmg"},
    # EY: SAP SuccessFactors' career-site builder on careers.ey.com, token
    # `host|site`. Places arrive as "City, Region, CC, Postcode" and are
    # rewritten with the country by name; "+N more" rows are placed from the
    # posting page's microdata. Robots disallows only apply/community routes.
    # `location` values are PLACES; territories with no location group
    # (Bermuda, Aruba) stay unplaced. The page names "EY" (microdata
    # hiringOrganization) but the probe reads no identity, so `unstated`; URLs
    # are careers.ey.com. Not curated: consulting's three slots go to BCG,
    # Bain and Accenture.
    "ey": {"display": "EY", "adapter": "successfactors", "board_token": "careers.ey.com|ey"},
    # Shopify's own careers page: the React Router loader data holds every
    # listed posting; its Ashby board answers 404. One response is the
    # listing, with no stated total. `location` values are PLACES, many of them
    # the region "Americas" (remote), which places as a region; the page names
    # no tenant (identity `unstated`); URLs are www.shopify.com. The rows carry
    # hiring-team names and emails, never read.
    "shopify": {"display": "Shopify", "adapter": "shopify", "board_token": "shopify"},
    # TikTok's own careers search API, read against its `data.count`.
    # `location` values are PLACES ("San Jose, California, United States of
    # America"); the rows name no employer (the board is TikTok's by header and
    # host), so identity is `unstated`; apply URLs are careers.tiktok.com. The
    # token names nothing: the route is fixed.
    "tiktok": {"display": "TikTok", "adapter": "tiktok", "board_token": "tiktok"},
    # Oracle Cloud HCM tenants, token `host|site`. A posting counted but not
    # listable is accounted for by the workplace-type facet partition.
    # `location` values are PLACES ("Burnaby, BC, Canada"); the API names no
    # tenant (identity `unstated`); apply URLs are the tenant's CX site on
    # oraclecloud.com, which Fortinet's own careers page links.
    "fortinet": {"display": "Fortinet", "adapter": "oracle", "board_token": "edel.fa.us2.oraclecloud.com|CX_2001"},
    # Atlassian's own careers endpoint, not its iCIMS hosts. One response holds
    # the page's whole list. `location` values are PLACES ("San Francisco,
    # United States", "UK" for remote-in-country); the listing names no tenant
    # (identity `unstated`); apply URLs are Atlassian's iCIMS portal pages. The
    # token names nothing: the route is fixed.
    "atlassian": {"display": "Atlassian", "adapter": "atlassian", "board_token": "atlassian"},
    # SmartRecruiters. The board route unless the tenant publishes no board on
    # SmartRecruiters; route detection moves a company between the two at scan
    # time. The listing is read per location group; `location` values are
    # PLACES (the group label, then the posting's structured address); the
    # board names the company ("Careers at ServiceNow"); apply URLs are
    # `jobs.smartrecruiters.com`, not the employer's domain. Ubisoft's
    # identifier is `Ubisoft2` (`Ubisoft` is an empty tenant). Wise's board
    # redirects to its own `wise.jobs`, so it is on the walled API route and is
    # collected only after the user consents.
    "servicenow": {"curated": True, "display": "ServiceNow", "adapter": "smartrecruiters", "board_token": "ServiceNow"},
    "ubisoft": {"display": "Ubisoft", "adapter": "smartrecruiters", "board_token": "Ubisoft2"},
    "roland-berger": {"display": "Roland Berger", "adapter": "smartrecruiters", "board_token": "RolandBerger"},
    "wise": {"display": "Wise", "adapter": "smartrecruiters_api", "board_token": "Wise"},
    # --- Lever boards (api.lever.co/v0/postings/{site}) ----------------------
    # All three are on the GLOBAL deployment, which is a record and not a
    # default: Lever runs separate tenant namespaces per region and a wrong
    # region 404s exactly like a wrong token, so the region has to be carried
    # from the moment we resolve it.
    "palantir": {"curated": True, "display": "Palantir", "adapter": "lever", "board_token": "palantir", "board_region": "global"},
    "shield-ai": {"curated": True, "display": "Shield AI", "adapter": "lever", "board_token": "shieldai", "board_region": "global"},
    "zoox": {"display": "Zoox", "adapter": "lever", "board_token": "zoox", "board_region": "global"},
}

#: Companies read through another company's connector, with the token it reads
#: them by: `google-deepmind` rides the Google connector family. Not in
#: `CATALOG`, whose rows are boards of their own (`company_discovery` reports
#: these as `family`).
FAMILY_CONNECTORS: dict[str, dict] = {
    "google-deepmind": {
        "adapter": "google",
        "board_token": "DeepMind",
        "label": "Google connector family",
    }
}
