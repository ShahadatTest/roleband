## Errors (docs/copy.md). Key: error- plus the code the API or
## the transport sends (backend tracker/api/errors.py ErrorCode). An error says
## what happened, then the next step, or says next=none.

# kind=error
error-generic = Couldn't do that. Try again.
# kind=error note="The API did not answer at all: down, or the app is not running"
error-offline = RoleBand isn't answering. Check that RoleBand is running, then try again.
# kind=error note="The API answered with a failure it did not explain"
error-server = Something went wrong. Try again.
# kind=error note="The request was malformed: a defect, not the person's doing"
error-invalid-input = Couldn't use that request. Try again.

## Something named does not exist
# kind=error next=none
error-job-not-found = This role no longer exists.
# kind=error next=none
error-company-not-found = That company can't be found.
# kind=error next=none
error-company-profile-not-found = There's no profile for that company.
# kind=error next=none
error-local-model-not-found = That local model connection isn't saved anymore.
# kind=error next=none
error-cloud-model-not-found = That AI connection isn't saved anymore.
# kind=error next=none
error-notification-not-found = That notification is gone.
# kind=error next=none
error-link-not-found = Those postings aren't linked anymore.
# kind=error next=none
error-suggestion-not-found = That suggestion is gone.
# kind=error next=none
error-recipe-not-found = That recipe is gone.
# kind=error next=none
error-rule-not-found = That exclusion is gone.
# kind=error next=none
error-cluster-not-found = That group is gone.
# kind=error next=none
error-fit-band-not-found = That fit grade can't be found.
# kind=error
error-schedule-not-found = That company has no schedule yet. Try again when the scan ends.
# kind=error next=none
error-page-not-found = There's nothing here.
# kind=error next=none
error-plugin-not-found = That plugin isn't installed anymore.

## What was asked cannot be done, and why
# kind=error next=none note="The site's robots rules or bot wall; same words as the consent dialog"
error-careers-page-refused = That careers site limits automated collection, so it can't be added.
# kind=error
error-careers-page-unreachable = That careers page isn't answering. Try again.
# kind=error next=none
error-company-conflict = That company is already on the list.
# kind=error
error-company-refused = Couldn't add that company. Check the link and try again.
# kind=error next=none
error-consent-required = Following that company needs your answer to its warning first.
# kind=error
error-scope-refused = Couldn't save your answers. Try again.
# kind=error
error-schedule-refused = Couldn't move that scan. Try again.
# kind=error next=none note="$companies is a list of company names"
error-scheduling-unavailable = { $companies } can't be scanned on a timer.
# kind=error next=none
error-discovery-unsupported = { $company } can't be checked this way.
# kind=error
error-manual-scan-queued = A scan you started is still waiting. Try again when the scan ends.
# kind=error
error-switch-running = The ranking is already updating. Try again when it ends.
# kind=error next=none
error-switch-not-started = The change is saved. Ranking updates on the next scan.
# kind=error next=none
error-no-switch-running = Nothing is updating now.
# kind=error
error-switch-not-stopped = Couldn't stop the update, and your model choice is unchanged. Try again.
# kind=error note="Saving a stock price key: Tiingo answered that the key is not valid"
error-price-key-refused = Tiingo refused this key, so it wasn't saved. Check it in your Tiingo account and try again.
# kind=error next=none
error-switch-not-managed = This update wasn't started here, so it can't be stopped here.
# kind=error next=none
error-server-not-managed = This server can't be started or stopped from here.
# kind=error
error-model-unreachable = Couldn't reach the model. Check that it is running, then try again.
# kind=error
error-local-models-off = Local AI is turned off. Turn it on in Settings › AI.
# kind=error
error-ai-egress-off = Cloud AI is turned off, so nothing was sent. Turn it on in Settings › AI.
# kind=error
error-no-local-model = No local model is chosen. Add one in Settings › AI.
# kind=error next=none note="Saving an AI connection after an update: the saved connections no longer validate, so the save was refused and nothing was lost"
error-model-profiles-unreadable = Your saved AI connections couldn't be read, so nothing was changed.
# kind=error next=none
error-link-to-itself = A posting can't be linked to itself.
# kind=error next=none
error-already-linked = These postings are already linked.
# kind=error
error-verdict-decided = You already decided these. Change it in History.
# kind=error next=none
error-pair-refused = These postings can't be linked.
# kind=error next=none
error-not-a-member = That posting isn't in this set anymore.
# kind=error next=none
error-suggestion-decided = You already answered that suggestion.
# kind=error next=none
error-last-world = Keep at least one world on your radar.
# kind=error
error-recipe-invalid = That recipe has problems. Fix them and try again.
# kind=error next=none
error-recipe-conflict = That company is already scanned another way.
# kind=error
error-usage-catalogue-changed = What's shared changed while you were choosing. Try again.

## Plugins: what an install allows, and what the person saw
# kind=error next=none
error-plugin-not-runnable = That plugin runs only once it's approved and turned on.
# kind=error
error-plugin-running = That plugin is already updating. Try again when it ends.
# kind=error note="The plugin's code or permissions changed after the approval dialog opened"
error-plugin-approval-stale = That plugin changed since you looked at it, so it isn't approved. Try again.
# kind=error next=none
error-plugin-still-enabled = A plugin's data can be removed only while it's turned off.
# kind=error note="The typed confirmation did not match the name the dialog asked for"
error-plugin-confirm-mismatch = What you typed doesn't match the name shown. Try again.
# kind=error note="Remove data, refused while estimates still read the plugin's data (its turn-off has not finished updating them)"
error-plugin-estimates-moving = Estimates are still updating to leave its data out. Try again when it ends.
# kind=error note="A pin refused on company size while a plugin answers it: a pin is RoleBand's own, and RoleBand's own isn't shown there"
error-field-answered-by-plugin = A plugin answers this while it's on, so a value you set here wouldn't show. Turn it off in Settings › Plugins.
