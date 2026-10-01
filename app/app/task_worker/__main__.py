"""``python -m app.task_worker``: the standalone durable worker process."""

from app.task_worker import main

if __name__ == "__main__":
    raise SystemExit(main())
