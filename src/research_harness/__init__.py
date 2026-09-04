"""Research Development Harness (RDH) runtime.

A fully repository-local harness that keeps research intent, implementation,
evidence and researcher understanding recoverable from Git + GitHub.

This package is deliberately standard-library only (Python 3.11+).
"""

__all__ = [
    "RUNTIME_VERSION",
    "BUNDLE_VERSION",
    "RECORD_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "MIN_RUNTIME_VERSION",
]

#: Version of the Python runtime shipped in this package.
RUNTIME_VERSION = "0.1.0"

#: Version of the vendored policy/workflow/template/skill bundle.
BUNDLE_VERSION = "0.1.0"

#: Schema version written into durable GitHub record markers.
RECORD_SCHEMA_VERSION = 1

#: Schema version of ``.research-harness/manifest.toml``.
MANIFEST_SCHEMA_VERSION = 1

#: Oldest runtime version whose adopted repositories this runtime can drive.
MIN_RUNTIME_VERSION = "0.1.0"
