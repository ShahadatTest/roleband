"""The SDK's own version and the wire protocol it speaks.

`SDK_VERSION` is what a manifest's `sdk` specifier is checked against.
`PROTOCOL_VERSION` is the stdio protocol: the host's `start` message names
it, and a runner that speaks another refuses the run.
"""

SDK_VERSION = "1.0.0"
#: Every SDK release, oldest first; the last is `SDK_VERSION`. A manifest's
#: `sdk` range may admit only releases that know every key it uses
#: (`manifest.KEY_SINCE`).
SDK_RELEASES = ("1.0.0",)
PROTOCOL_VERSION = 1
