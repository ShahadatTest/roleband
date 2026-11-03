## Usage sharing: the consent screen and Settings > Privacy (docs/architecture.md).
## "us", not the product's name; the lead gives a reason to help (a free, open-source project
## that improves every release); one warm answer, "Happy to help", that shares every kind
## listed, and "No thanks" beside it. Nothing is pre-ticked: a ticked box is not a consent
## (CJEU Planet49), so choosing kinds is a link that opens clear boxes. RoleBand records no
## sessions. The consent sentences are pinned (pinned.en.json): the screen stores exactly
## these words as what was agreed.

# kind=heading
privacy-consent-title = Help us improve
# kind=consent
privacy-consent-intro = We're free and open source, and we get better with every release. Anonymous data shows us what to fix and what to build next.
# kind=label
privacy-group-usage = Anonymous usage data
# kind=consent
privacy-group-usage-detail = Which screens and features you use, and how scans go.
# kind=label
privacy-group-crashes = Crash reports
# kind=consent
privacy-group-crashes-detail = What broke and where, so we can fix it fast.
# kind=label
privacy-group-questions = Feedback surveys
# kind=consent
privacy-group-questions-detail = An occasional one-question survey. Skip any you like.
# kind=consent
privacy-never = Never sent: company names, role titles, compensation, your CV or anything you type.
# kind=consent
privacy-consent-change = Change it any time in Settings › Privacy.
# kind=button
privacy-choose = Let me choose
# kind=button
privacy-no-thanks = No thanks
# kind=button
privacy-happy-to-help = Happy to help
# kind=error
privacy-save-error = Couldn't save your choice. Try again.

## Settings > Privacy

# kind=heading note="The Settings card's own title, naming its tab; the consent question's title heads its switches"
privacy-settings-title = Privacy
# kind=sentence
privacy-settings-intro = Each kind of sharing is off until you turn it on. Turning one off stops it at once.
# kind=sentence
privacy-settings-blocked = Sharing is off on this computer: { $switch } is set.
# kind=sentence
privacy-settings-stale = What this kind covers has grown since you chose. Turn it on again to keep sharing.
# kind=heading
privacy-settings-load-failed = Couldn't load your privacy choices
# kind=sentence
privacy-settings-refresh-failed = Couldn't refresh your privacy choices. Showing the last result.
# kind=label
privacy-install-id = Your install ID
# kind=sentence
privacy-install-id-detail = A random ID, not linked to you. Reset it and nothing new is linked to what was sent before.
# kind=label
privacy-install-id-none = None yet
# kind=button
privacy-reset-id = Reset ID
# kind=label
privacy-next-send = Next send
# kind=status note="How many events wait to be sent; a fact, so a count and its noun only"
privacy-next-send-count = { $count ->
    [one] { $count } event
   *[other] { $count } events
}
# kind=sentence note="Under Next send: when the waiting events leave"
privacy-next-send-detail = Waits for the daily send.
# kind=label
privacy-last-sent = Last sent
# kind=label
privacy-last-sent-never = Never
# kind=button
privacy-show-next = Show what's sent
# kind=label
privacy-sent-recently = Sent recently
# kind=sentence note="Under Sent recently: what the list holds"
privacy-sent-recently-detail = What left this machine in the last 30 days, and what this window sent since it opened.
# kind=button
privacy-show-sent = Show the list
# kind=button
privacy-hide-sent = Hide the list
# kind=sentence
privacy-sent-none = Nothing was sent in the last 30 days.
# kind=status note="One sent row's count: how many times that event was counted"
privacy-sent-count = { $count ->
    [one] once
   *[other] { $count } times
}
# kind=status note="A row the dashboard itself sent, beside the daily send's rows"
privacy-sent-from-browser = from this window
# kind=status
privacy-sent-loading = Loading what was sent…
# kind=heading
privacy-sent-load-failed = Couldn't load what was sent
