"""Package version and wire-schema version.

`SCHEMA_VERSION` is the ingest wire-contract version (decision C3): every event the
SDK ships carries it, and the collector keeps a backward-compat layer keyed on it.
Bump it whenever the span/score payload shape changes.
"""

__version__ = "0.1.0"

# Wire-schema version for /v1/ingest and /v1/scores payloads.
SCHEMA_VERSION = 1
