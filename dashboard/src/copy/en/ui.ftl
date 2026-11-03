### eager: the shell imports this file, so every message in it ships in the shell
### (docs/copy.md section 3). The compiler numbers its messages first.

## Primitives (src/ui/)

# kind=status note="The loading line when a caller names no whole message of its own"
ui-loading = Loading…
# kind=heading note="The failure heading when a caller names no whole message of its own"
ui-load-failed = Couldn't load this
# kind=sentence
ui-load-failed-hint = Couldn't get it just now.
# kind=aria note="$label names the overlay being closed"
ui-close-label = Close { $label }
# kind=aria
ui-dismiss = Dismiss
# kind=aria wording=as-is note="InfoTip's default name; the shell shows it"
ui-info-tip-more-information = More information
