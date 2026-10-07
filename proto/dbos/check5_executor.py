"""Check 5, shared executor: an async DBOS API called on a cohort loop makes
DBOS's process-wide thread pool that loop's default executor; when the
cohort's `asyncio.run` returns it shuts the default executor down, and every
later DBOS call in the process fails.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading

from dbos import DBOS


@DBOS.workflow()
def trivial(x: int) -> int:
    return x + 1


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="dbos-c5x-")
    DBOS(config={"name": "probe", "system_database_url": f"sqlite:///{workdir}/probe.db", "log_level": "ERROR"})
    DBOS.launch()
    before = DBOS.start_workflow(trivial, 1).get_result()

    def cohort() -> None:
        async def body() -> None:
            await DBOS.list_workflows_async(limit=1)  # any async DBOS API

        asyncio.run(body())  # a cohort loop ending normally

    thread = threading.Thread(target=cohort)
    thread.start()
    thread.join()
    try:
        after: object = DBOS.start_workflow(trivial, 2).get_result()
    except Exception as exc:
        after = f"{type(exc).__name__}: {exc}"
    print(json.dumps({"before_cohort_exit": before, "after_cohort_exit": after}, indent=2))
    DBOS.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
