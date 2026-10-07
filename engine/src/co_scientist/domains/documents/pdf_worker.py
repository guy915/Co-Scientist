from __future__ import annotations

import resource
import sys

from co_scientist.domains.documents.ingest import _pdf_worker_main


def _set_resource_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (115, 115))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024**2, 8 * 1024**2))


if __name__ == "__main__":
    _set_resource_limits()
    sys.exit(_pdf_worker_main())
