# Interaction Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Chat tab to RunDetail that lets users steer the running AI system and ask questions about it, with the system posting milestone updates automatically.

**Architecture:** App-layer overlay — no engine changes. A `messages` SQLite table stores user steering and Q&A. Steering messages are injected as `preferences` text before each supervisor call. Q&A uses a direct LiteLLM call with run context. A new `ChatTab` frontend component polls `/api/runs/{id}/messages`.

**Tech Stack:** Python/FastAPI/SQLite (backend), React 19/TypeScript/Tailwind/Bun (frontend), LiteLLM (Q&A LLM calls)

---

## File Map

| File | Change |
|---|---|
| `ai-coscientist-app/app/store.py` | Add `messages` table to `_SCHEMA`; add 4 store functions + `MessageRow` dataclass |
| `ai-coscientist-app/app/config.py` | Add `chat_model_name: str \| None = None` setting |
| `ai-coscientist-app/app/runs.py` | Add 3 endpoints + 3 Pydantic request models |
| `ai-coscientist-app/app/engine_adapter.py` | Read pending steering before engine call; emit milestone messages per node |
| `ai-coscientist-app/app/mock_workflow.py` | Read and apply pending steering at each iteration boundary |
| `ai-coscientist-app/frontend/src/api/runs.ts` | Add `Message` interface + `listMessages`, `sendMessage`, `askQuestion` |
| `ai-coscientist-app/frontend/src/hooks/useMessages.ts` | New hook — polls messages, exposes send/ask actions |
| `ai-coscientist-app/frontend/src/workbench/components/tabs/ChatTab.tsx` | New component — unified feed + input |
| `ai-coscientist-app/frontend/src/workbench/pages/RunDetail.tsx` | Add `"chat"` to TABS + render `ChatTab` |
| `ai-coscientist-app/tests/test_messages.py` | New test file |

---

## Task 1: messages table + store functions

**Files:**
- Modify: `ai-coscientist-app/app/store.py`
- Test: `ai-coscientist-app/tests/test_messages.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_messages.py`:

```python
"""Tests for the messages store layer."""
from __future__ import annotations

from app import store


def test_append_and_list_messages(isolated_db):
    store.create_run("rg", "standard", "mock", {}, client_id="c1", db_path=isolated_db)
    runs = store.list_runs(client_id="c1", db_path=isolated_db)
    run_id = runs[0].id

    store.append_message(run_id, "user", "focus on cytokines", "steering", db_path=isolated_db)
    store.append_message(run_id, "system", "Research plan ready", "milestone", db_path=isolated_db)

    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert len(msgs) == 2
    assert msgs[0].sender == "user"
    assert msgs[0].kind == "steering"
    assert msgs[0].applied is False
    assert msgs[1].kind == "milestone"


def test_get_pending_steering(isolated_db):
    store.create_run("rg", "standard", "mock", {}, client_id="c1", db_path=isolated_db)
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    store.append_message(run_id, "user", "steer A", "steering", db_path=isolated_db)
    store.append_message(run_id, "system", "milestone msg", "milestone", db_path=isolated_db)
    store.append_message(run_id, "user", "steer B", "steering", db_path=isolated_db)

    pending = store.get_pending_steering(run_id, db_path=isolated_db)
    assert len(pending) == 2
    assert all(m.kind == "steering" for m in pending)
    assert all(m.applied is False for m in pending)


def test_mark_steering_applied(isolated_db):
    store.create_run("rg", "standard", "mock", {}, client_id="c1", db_path=isolated_db)
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    store.append_message(run_id, "user", "steer A", "steering", db_path=isolated_db)
    store.append_message(run_id, "user", "steer B", "steering", db_path=isolated_db)

    pending = store.get_pending_steering(run_id, db_path=isolated_db)
    ids = [m.id for m in pending]
    store.mark_steering_applied(ids, db_path=isolated_db)

    after = store.get_pending_steering(run_id, db_path=isolated_db)
    assert len(after) == 0

    all_msgs = store.list_messages(run_id, db_path=isolated_db)
    assert all(m.applied is True for m in all_msgs)


def test_message_to_dict(isolated_db):
    store.create_run("rg", "standard", "mock", {}, client_id="c1", db_path=isolated_db)
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    msg = store.append_message(run_id, "user", "hello", "steering", db_path=isolated_db)
    d = msg.to_dict()
    assert d["sender"] == "user"
    assert d["content"] == "hello"
    assert d["kind"] == "steering"
    assert d["applied"] is False
    assert "id" in d
    assert "created_at" in d
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd ai-coscientist-app && pytest tests/test_messages.py -v 2>&1 | head -20
```

Expected: `AttributeError: module 'app.store' has no attribute 'append_message'`

- [ ] **Step 3: Add the messages table to `_SCHEMA` in `store.py`**

In `store.py`, append to the `_SCHEMA` string (just before the closing `"""`):

```python
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    sender     TEXT NOT NULL,
    content    TEXT NOT NULL,
    kind       TEXT NOT NULL,
    created_at REAL NOT NULL,
    applied    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_run ON messages(run_id, id);
```

- [ ] **Step 4: Add `MessageRow` dataclass and 4 store functions to `store.py`**

Add after the `RunRow` dataclass (around line 262):

```python
@dataclass
class MessageRow:
    id: int
    run_id: str
    sender: str
    content: str
    kind: str
    created_at: float
    applied: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "sender": self.sender,
            "content": self.content,
            "kind": self.kind,
            "created_at": self.created_at,
            "applied": self.applied,
        }
```

Add at the end of `store.py`:

```python
# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def append_message(
    run_id: str,
    sender: str,
    content: str,
    kind: str,
    db_path: str | None = None,
) -> "MessageRow":
    now = _now()
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO messages (run_id, sender, content, kind, created_at, applied) VALUES (?,?,?,?,?,0)",
            (run_id, sender, content, kind, now),
        )
        msg_id = cur.lastrowid
    return MessageRow(id=msg_id, run_id=run_id, sender=sender, content=content, kind=kind, created_at=now, applied=False)


def list_messages(run_id: str, db_path: str | None = None) -> list["MessageRow"]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, run_id, sender, content, kind, created_at, applied FROM messages "
            "WHERE run_id=? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
        return [
            MessageRow(
                id=r["id"],
                run_id=r["run_id"],
                sender=r["sender"],
                content=r["content"],
                kind=r["kind"],
                created_at=r["created_at"],
                applied=bool(r["applied"]),
            )
            for r in rows
        ]


def get_pending_steering(run_id: str, db_path: str | None = None) -> list["MessageRow"]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, run_id, sender, content, kind, created_at, applied FROM messages "
            "WHERE run_id=? AND kind='steering' AND applied=0 ORDER BY id ASC",
            (run_id,),
        ).fetchall()
        return [
            MessageRow(
                id=r["id"],
                run_id=r["run_id"],
                sender=r["sender"],
                content=r["content"],
                kind=r["kind"],
                created_at=r["created_at"],
                applied=bool(r["applied"]),
            )
            for r in rows
        ]


def mark_steering_applied(ids: list[int], db_path: str | None = None) -> None:
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    with connect(db_path) as conn:
        conn.execute(f"UPDATE messages SET applied=1 WHERE id IN ({placeholders})", ids)
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
cd ai-coscientist-app && pytest tests/test_messages.py -v
```

Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
cd ai-coscientist-app && git add app/store.py tests/test_messages.py
git commit -m "feat: add messages table and store functions"
```

---

## Task 2: config + endpoint scaffolding

**Files:**
- Modify: `ai-coscientist-app/app/config.py`
- Modify: `ai-coscientist-app/app/runs.py`

- [ ] **Step 1: Add `chat_model_name` to `config.py`**

In `config.py`, add after the `supervisor_model_name` line (line 14):

```python
# chat_model_name: model used for Q&A responses in the Chat tab.
# Defaults to model_name if not set. Use a cheaper/faster model for snappy answers.
chat_model_name: str | None = None
```

- [ ] **Step 2: Add Pydantic request models and the 3 new endpoints to `runs.py`**

Add these Pydantic models after the existing `StartRunRequest` model:

```python
class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
```

Then add these three endpoints at the end of `runs.py`:

```python
# ---------------------------------------------------------------------------
# Chat / interaction endpoints
# ---------------------------------------------------------------------------


@router.post("/{run_id}/messages")
async def send_message(run_id: str, req: SendMessageRequest) -> dict[str, Any]:
    """Queue a user steering message for the next iteration."""
    _run_or_404(run_id)
    msg = store.append_message(run_id, "user", req.content, "steering", db_path=_db_path())
    return {**msg.to_dict(), "status": "queued"}


@router.get("/{run_id}/messages")
async def list_messages(run_id: str) -> dict[str, Any]:
    """Return all messages for a run in chronological order."""
    _run_or_404(run_id)
    msgs = store.list_messages(run_id, db_path=_db_path())
    return {"messages": [m.to_dict() for m in msgs]}


@router.post("/{run_id}/messages/ask")
async def ask_question(run_id: str, req: AskRequest) -> StreamingResponse:
    """Answer a question about the run using a fast LLM, streaming the response."""
    run = _run_or_404(run_id)

    question_msg = store.append_message(run_id, "user", req.question, "qa", db_path=_db_path())

    hypotheses = store.list_hypotheses(run_id, db_path=_db_path())
    reviews = store.list_reviews(run_id, db_path=_db_path())
    matches = store.list_matches(run_id, db_path=_db_path())
    history = store.list_messages(run_id, db_path=_db_path())[:-1]  # exclude just-stored question

    top_hyps = sorted(hypotheses, key=lambda h: -int(h.get("elo_rating") or 1200))[:5]
    hyp_lines = "\n".join(
        f"- [{h['title']}] Elo {h.get('elo_rating', 1200)}, {h.get('win_count', 0)}W/{h.get('loss_count', 0)}L"
        for h in top_hyps
    )
    review_lines = "\n".join(
        f"- {r['reviewer_agent']} on {r['hypothesis_id'][:8]}: {r['summary'][:120]}"
        for r in reviews[-5:]
    )
    match_lines = "\n".join(
        f"- Winner {m['winner_id'][:8]} (Elo {m['winner_elo_after']}) — {(m.get('rationale') or '')[:100]}"
        for m in matches[-3:]
    )
    conv_lines = "\n".join(
        f"{'User' if m.sender == 'user' else 'Assistant'}: {m.content}"
        for m in history[-10:]
    )

    system_prompt = (
        f"You are a concise research assistant helping the user understand an ongoing "
        f"AI-driven hypothesis generation run.\n\n"
        f"Research goal: {run.research_goal}\n\n"
        f"Top hypotheses by Elo:\n{hyp_lines or '(none yet)'}\n\n"
        f"Recent reviews:\n{review_lines or '(none yet)'}\n\n"
        f"Recent tournament matches:\n{match_lines or '(none yet)'}\n\n"
        f"Conversation history:\n{conv_lines or '(none)'}\n\n"
        f"Answer concisely and accurately. Do not repeat the question."
    )

    model = os.getenv("CHAT_MODEL_NAME") or os.getenv("MODEL_NAME", "deepseek/deepseek-chat")

    async def _stream() -> AsyncGenerator[str, None]:
        try:
            import litellm  # type: ignore[import-untyped]

            full: list[str] = []
            response = await litellm.acompletion(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": req.question},
                ],
                stream=True,
            )
            async for chunk in response:
                delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if delta:
                    full.append(delta)
                    yield f"data: {json.dumps({'type': 'chunk', 'content': delta})}\n\n"

            answer = "".join(full)
            store.append_message(run_id, "system", answer, "qa", db_path=_db_path())
            yield f"data: {json.dumps({'type': 'done', 'question_id': question_msg.id})}\n\n"
        except Exception as exc:
            logger.error("Q&A stream error for run %s: %s", run_id, exc)
            fallback = "Q&A requires a language model API key (set CHAT_MODEL_NAME or MODEL_NAME)."
            store.append_message(run_id, "system", fallback, "qa", db_path=_db_path())
            yield f"data: {json.dumps({'type': 'error', 'message': fallback})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
```

- [ ] **Step 3: Add tests for the endpoints to `test_messages.py`**

Append to `tests/test_messages.py`:

```python
# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

import time
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


def _make_run(client, goal="test goal"):
    res = client.post("/api/runs", json={"research_goal": goal, "profile": "standard"},
                      headers={"X-Client-ID": "test-client"})
    assert res.status_code == 200
    return res.json()["id"]


def test_send_message_endpoint(isolated_db):
    client = _client()
    run_id = _make_run(client)

    res = client.post(f"/api/runs/{run_id}/messages",
                      json={"content": "focus on cytokines"})
    assert res.status_code == 200
    data = res.json()
    assert data["kind"] == "steering"
    assert data["status"] == "queued"
    assert data["content"] == "focus on cytokines"


def test_send_message_always_stores_as_steering(isolated_db):
    """POST /messages always stores as steering; Q&A routing is the frontend's job."""
    client = _client()
    run_id = _make_run(client)

    res = client.post(f"/api/runs/{run_id}/messages",
                      json={"content": "Why did hypothesis 3 drop?"})
    assert res.status_code == 200
    assert res.json()["kind"] == "steering"


def test_list_messages_endpoint(isolated_db):
    client = _client()
    run_id = _make_run(client)

    client.post(f"/api/runs/{run_id}/messages", json={"content": "steer A"})
    client.post(f"/api/runs/{run_id}/messages", json={"content": "steer B"})

    res = client.get(f"/api/runs/{run_id}/messages")
    assert res.status_code == 200
    msgs = res.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["content"] == "steer A"
    assert msgs[1]["content"] == "steer B"


def test_list_messages_404_on_unknown_run(isolated_db):
    client = _client()
    res = client.get("/api/runs/nonexistent-id/messages")
    assert res.status_code == 404
```

- [ ] **Step 4: Run tests**

```bash
cd ai-coscientist-app && pytest tests/test_messages.py -v
```

Expected: all tests pass (the ask endpoint test is not written yet — that requires a real LLM; skip it for now)

- [ ] **Step 5: Commit**

```bash
cd ai-coscientist-app && git add app/config.py app/runs.py tests/test_messages.py
git commit -m "feat: add chat endpoints and message classification"
```

---

## Task 3: steering injection in engine_adapter + mock_workflow

**Files:**
- Modify: `ai-coscientist-app/app/engine_adapter.py`
- Modify: `ai-coscientist-app/app/mock_workflow.py`

- [ ] **Step 1: Add tests for steering injection to `test_messages.py`**

Append to `tests/test_messages.py`:

```python
def test_steering_messages_applied_after_run(isolated_db):
    """Steering messages sent before a run starts should be marked applied when the run completes."""
    client = _client()
    run_id = _make_run(client, goal="test steering injection")

    # Send a steering message before starting the run.
    client.post(f"/api/runs/{run_id}/messages",
                json={"content": "focus on apoptosis pathways", "kind": "steering"})

    # Verify it starts as not applied.
    msgs_before = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
    assert msgs_before[0]["applied"] is False

    # Start and wait for completion.
    client.post(f"/api/runs/{run_id}/start", json={})
    deadline = time.time() + 20.0
    while time.time() < deadline:
        r = client.get(f"/api/runs/{run_id}")
        if r.json()["status"] == "completed":
            break
        time.sleep(0.1)

    msgs_after = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
    steering = [m for m in msgs_after if m["kind"] == "steering"]
    assert len(steering) == 1
    assert steering[0]["applied"] is True


def test_milestone_messages_generated_after_run(isolated_db):
    """Milestone messages should be generated as the run progresses."""
    client = _client()
    run_id = _make_run(client, goal="test milestone generation")

    client.post(f"/api/runs/{run_id}/start", json={})
    deadline = time.time() + 20.0
    while time.time() < deadline:
        r = client.get(f"/api/runs/{run_id}")
        if r.json()["status"] == "completed":
            break
        time.sleep(0.1)

    msgs = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
    milestones = [m for m in msgs if m["kind"] == "milestone"]
    assert len(milestones) >= 1
    kinds = [m["sender"] for m in milestones]
    assert all(k == "system" for k in kinds)
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
cd ai-coscientist-app && pytest tests/test_messages.py::test_steering_messages_applied_after_run tests/test_messages.py::test_milestone_messages_generated_after_run -v
```

Expected: both FAIL (applied stays False, no milestones)

- [ ] **Step 3: Add steering injection and milestone helper to `engine_adapter.py`**

Add this helper function just before `run_workflow` in `engine_adapter.py` (around line 82):

```python
def _format_milestone(node_type: str, payload: dict[str, Any]) -> str | None:
    """Return a human-readable milestone string for key node events, or None."""
    if node_type in ("supervisor", "supervisor.plan"):
        return "Research plan ready — supervisor complete"
    if node_type == "generate":
        count = payload.get("count") or payload.get("hypothesis_count", 0)
        itr = payload.get("iteration", 0)
        label = f"iteration {itr}" if itr else "initial"
        return f"{count} hypotheses generated ({label})"
    if node_type == "ranking":
        count = payload.get("hypothesis_count") or payload.get("matches_count", 0)
        itr = payload.get("iteration", 0)
        return f"Tournament complete (iteration {itr}, {count} matches)"
    if node_type == "meta_review":
        return "Meta-review complete"
    if node_type == "evolve":
        count = payload.get("count") or payload.get("hypothesis_count", 0)
        itr = payload.get("iteration", 0)
        return f"{count} hypotheses evolved (iteration {itr})"
    return None
```

- [ ] **Step 4: Modify the mock path in `run_workflow` to apply pre-run steering and emit milestones**

In `engine_adapter.py`, replace the mock path (lines ~100-111):

```python
    if provider == "mock":
        # Apply any steering queued before the run started.
        pre_run_steering = store.get_pending_steering(run_id, db_path=db_path)
        if pre_run_steering:
            store.mark_steering_applied([m.id for m in pre_run_steering], db_path=db_path)

        async for event in run_mock_workflow(
            run_id=run_id,
            research_goal=research_goal,
            profile=profile,
            config=cfg,
            db_path=db_path,
            cancelled=cancelled,
            sleep_seconds=sleep_seconds,
        ):
            milestone = _format_milestone(event.get("type", ""), event.get("payload", {}))
            if milestone:
                store.append_message(run_id, "system", milestone, "milestone", db_path=db_path)
            yield event
        return
```

- [ ] **Step 5: Modify `mock_workflow.py` to read and apply steering at each iteration boundary**

In `mock_workflow.py`, locate the iteration loop `for itr in range(1, cfg["max_iterations"] + 2):` (around line 316). Add steering injection at the TOP of that loop, immediately after the `for itr in range(...):`  line:

```python
    for itr in range(1, cfg["max_iterations"] + 2):
        # Apply any pending steering messages before this iteration.
        pending = store.get_pending_steering(run_id, db_path=db_path)
        if pending:
            steering_note = "; ".join(m.content for m in pending)
            logger.info("run %s iteration %d: applying steering: %s", run_id, itr, steering_note)
            store.mark_steering_applied([m.id for m in pending], db_path=db_path)
        # rest of existing loop continues here...
```

- [ ] **Step 6: Add opts support to the real engine call in `engine_adapter.py`**

In the engine path, just before the `generator = HypothesisGenerator(...)` instantiation (around line 215), add:

```python
    # Read any pending steering messages and pass as initial preferences.
    pending_steering = store.get_pending_steering(run_id, db_path=db_path)
    initial_opts: dict[str, Any] = {}
    if pending_steering:
        guidance = "\n".join(f"- {m.content}" for m in pending_steering)
        initial_opts["preferences"] = f"User steering guidance:\n{guidance}"
        store.mark_steering_applied([m.id for m in pending_steering], db_path=db_path)
```

Then update the `generate_hypotheses` call to pass opts:

```python
        async for node_name, state in generator.generate_hypotheses(  # type: ignore[union-attr]
            research_goal=research_goal,
            stream=True,
            run_id=run_id,
            opts=initial_opts if initial_opts else None,
        ):
```

Also add milestone emission inside that `async for` loop, after the `payload = {...}` dict is built and before `yield await _emit(...)`:

```python
            milestone = _format_milestone(node_name, payload)
            if milestone:
                store.append_message(run_id, "system", milestone, "milestone", db_path=db_path)
```

- [ ] **Step 7: Run the new tests**

```bash
cd ai-coscientist-app && pytest tests/test_messages.py -v
```

Expected: all tests pass

- [ ] **Step 8: Run full test suite to check for regressions**

```bash
cd ai-coscientist-app && pytest --tb=short -q
```

Expected: all existing tests still pass

- [ ] **Step 9: Commit**

```bash
cd ai-coscientist-app && git add app/engine_adapter.py app/mock_workflow.py tests/test_messages.py
git commit -m "feat: inject steering messages and emit milestones during workflow"
```

---

## Task 4: frontend API types + functions

**Files:**
- Modify: `ai-coscientist-app/frontend/src/api/runs.ts`

- [ ] **Step 1: Add `Message` interface and 3 API functions to `runs.ts`**

Add the `Message` interface after the existing `RunSummary` interface (around line 43):

```typescript
export interface Message {
  id: number;
  run_id: string;
  sender: "user" | "system";
  content: string;
  kind: "steering" | "qa" | "milestone";
  created_at: number;
  applied: boolean;
  status?: string;
}
```

Add these three functions at the end of `runs.ts`:

```typescript
export async function listMessages(runId: string): Promise<Message[]> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${runId}/messages`, {
    headers: clientHeaders(),
  });
  if (!res.ok) throw new Error(`listMessages ${res.status}`);
  const data = (await res.json()) as { messages: Message[] };
  return data.messages;
}

export async function sendMessage(
  runId: string,
  content: string,
  kind?: "steering" | "qa"
): Promise<Message> {
  const res = await fetch(`${API_BASE_URL}/api/runs/${runId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...clientHeaders() },
    body: JSON.stringify({ content, ...(kind ? { kind } : {}) }),
  });
  if (!res.ok) throw new Error(`sendMessage ${res.status}`);
  return (await res.json()) as Message;
}

export function askQuestionUrl(runId: string): string {
  return `${API_BASE_URL}/api/runs/${runId}/messages/ask`;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ai-coscientist-app/frontend && bun run check 2>&1 | tail -10
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd ai-coscientist-app && git add frontend/src/api/runs.ts
git commit -m "feat: add message API types and client functions"
```

---

## Task 5: useMessages hook

**Files:**
- Create: `ai-coscientist-app/frontend/src/hooks/useMessages.ts`

- [ ] **Step 1: Create the hook**

Create `frontend/src/hooks/useMessages.ts`:

```typescript
import { useCallback, useEffect, useRef, useState } from "react";
import {
  type Message,
  askQuestionUrl,
  listMessages,
  sendMessage,
} from "@/api/runs";

export interface UseMessagesResult {
  messages: Message[];
  isAnswering: boolean;
  error: string | null;
  sendSteering: (content: string) => Promise<void>;
  sendQuestion: (question: string) => Promise<void>;
}

export function useMessages(
  runId: string | null,
  isRunActive: boolean
): UseMessagesResult {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isAnswering, setIsAnswering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchMessages = useCallback(async () => {
    if (!runId) return;
    try {
      const msgs = await listMessages(runId);
      setMessages(msgs);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [runId]);

  // Initial fetch + poll while run is active.
  useEffect(() => {
    void fetchMessages();
    if (isRunActive) {
      pollRef.current = setInterval(() => void fetchMessages(), 3000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [fetchMessages, isRunActive]);

  const sendSteering = useCallback(
    async (content: string) => {
      if (!runId) return;
      const optimistic: Message = {
        id: Date.now(),
        run_id: runId,
        sender: "user",
        content,
        kind: "steering",
        created_at: Date.now() / 1000,
        applied: false,
        status: "queued",
      };
      setMessages((prev) => [...prev, optimistic]);
      try {
        const msg = await sendMessage(runId, content, "steering");
        setMessages((prev) =>
          prev.map((m) => (m.id === optimistic.id ? msg : m))
        );
      } catch (e) {
        setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [runId]
  );

  const sendQuestion = useCallback(
    async (question: string) => {
      if (!runId || isAnswering) return;
      setIsAnswering(true);

      const questionMsg: Message = {
        id: Date.now(),
        run_id: runId,
        sender: "user",
        content: question,
        kind: "qa",
        created_at: Date.now() / 1000,
        applied: false,
      };
      setMessages((prev) => [...prev, questionMsg]);

      const answerMsg: Message = {
        id: Date.now() + 1,
        run_id: runId,
        sender: "system",
        content: "",
        kind: "qa",
        created_at: Date.now() / 1000,
        applied: false,
      };
      setMessages((prev) => [...prev, answerMsg]);

      try {
        const url = askQuestionUrl(runId);
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question }),
        });
        if (!res.ok || !res.body) throw new Error(`ask failed: ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const event = JSON.parse(line.slice(6)) as {
                type: string;
                content?: string;
              };
              if (event.type === "chunk" && event.content) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === answerMsg.id
                      ? { ...m, content: m.content + event.content! }
                      : m
                  )
                );
              }
            } catch {
              // ignore malformed SSE line
            }
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setIsAnswering(false);
        // Refresh to get server-assigned IDs.
        void fetchMessages();
      }
    },
    [runId, isAnswering, fetchMessages]
  );

  return { messages, isAnswering, error, sendSteering, sendQuestion };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ai-coscientist-app/frontend && bun run check 2>&1 | tail -10
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd ai-coscientist-app && git add frontend/src/hooks/useMessages.ts
git commit -m "feat: add useMessages hook with polling and streaming Q&A"
```

---

## Task 6: ChatTab component

**Files:**
- Create: `ai-coscientist-app/frontend/src/workbench/components/tabs/ChatTab.tsx`

- [ ] **Step 1: Create `ChatTab.tsx`**

Create `frontend/src/workbench/components/tabs/ChatTab.tsx`:

```tsx
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import type { Run } from "@/api/runs";
import { useMessages } from "@/hooks/useMessages";

interface Props {
  run: Run | null;
}

type MessageMode = "auto" | "steering" | "qa";

function MilestoneRow({
  content,
  createdAt,
}: {
  content: string;
  createdAt: number;
}) {
  const time = new Date(createdAt * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <div
      className="flex items-start gap-2 py-1"
      style={{ color: "var(--md-sys-color-on-surface-variant)" }}
    >
      <span
        className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: "var(--md-sys-color-tertiary)" }}
        aria-hidden="true"
      />
      <span className="text-xs flex-1">{content}</span>
      <span className="text-xs shrink-0 opacity-60">{time}</span>
    </div>
  );
}

function UserBubble({
  content,
  kind,
  applied,
}: {
  content: string;
  kind: string;
  applied: boolean;
}) {
  const isSteering = kind === "steering";
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] space-y-1">
        <div
          className="rounded-xl px-3 py-2 text-sm"
          style={{
            backgroundColor: "var(--md-sys-color-primary-container)",
            color: "var(--md-sys-color-on-primary-container)",
          }}
        >
          {content}
        </div>
        {isSteering && (
          <div className="text-right">
            <span
              className="rounded-full px-2 py-0.5 text-xs"
              style={{
                backgroundColor: applied
                  ? "var(--md-sys-color-secondary-container)"
                  : "var(--md-sys-color-surface-variant)",
                color: applied
                  ? "var(--md-sys-color-on-secondary-container)"
                  : "var(--md-sys-color-on-surface-variant)",
              }}
            >
              {applied ? "Steering · applied" : "Steering · pending"}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function AnswerBubble({ content }: { content: string }) {
  return (
    <div className="pl-4">
      <div
        className="rounded-xl px-3 py-2 text-sm"
        style={{
          backgroundColor: "var(--md-sys-color-surface-variant)",
          color: "var(--md-sys-color-on-surface-variant)",
        }}
      >
        {content || <span className="opacity-40">Thinking…</span>}
      </div>
    </div>
  );
}

export function ChatTab({ run }: Props) {
  const isActive =
    run?.status === "running" || run?.status === "queued";
  const { messages, isAnswering, error, sendSteering, sendQuestion } =
    useMessages(run?.id ?? null, isActive);

  const [input, setInput] = useState("");
  const [mode, setMode] = useState<MessageMode>("auto");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const effectiveMode =
    mode === "auto"
      ? input.trim().endsWith("?") ||
        /^(why|what|how|when|who|which|explain|tell me|can you)\b/i.test(
          input.trim()
        )
        ? "qa"
        : "steering"
      : mode;

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isAnswering) return;
    setInput("");
    if (effectiveMode === "qa") {
      await sendQuestion(text);
    } else {
      await sendSteering(text);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void handleSend();
    }
  };

  if (!run) return null;

  return (
    <div className="flex flex-col gap-0" style={{ minHeight: "400px" }}>
      {/* Feed */}
      <div className="flex-1 space-y-2 overflow-y-auto pb-4">
        {messages.length === 0 && (
          <p
            className="text-sm py-6 text-center"
            style={{ color: "var(--md-sys-color-on-surface-variant)" }}
          >
            {isActive
              ? "Milestone updates will appear here. Send a message to steer the run or ask a question."
              : "No messages for this run."}
          </p>
        )}
        {messages.map((msg) => {
          if (msg.kind === "milestone") {
            return (
              <MilestoneRow
                key={msg.id}
                content={msg.content}
                createdAt={msg.created_at}
              />
            );
          }
          if (msg.sender === "user") {
            return (
              <UserBubble
                key={msg.id}
                content={msg.content}
                kind={msg.kind}
                applied={msg.applied}
              />
            );
          }
          if (msg.kind === "qa") {
            return <AnswerBubble key={msg.id} content={msg.content} />;
          }
          return null;
        })}
        <div ref={bottomRef} />
      </div>

      {/* Error */}
      {error && (
        <p
          className="text-xs mb-2"
          style={{ color: "var(--md-sys-color-error)" }}
        >
          {error}
        </p>
      )}

      {/* Input area */}
      {isActive && (
        <div
          className="rounded-xl border p-2 space-y-2"
          style={{
            borderColor: "var(--md-sys-color-outline-variant)",
            backgroundColor: "var(--md-sys-color-surface-container-low)",
          }}
        >
          <textarea
            className="w-full resize-none bg-transparent text-sm outline-none placeholder:opacity-50"
            style={{ color: "var(--md-sys-color-on-surface)" }}
            placeholder={
              effectiveMode === "qa"
                ? "Ask a question… (Ctrl+Enter to send)"
                : "Steer the run… (Ctrl+Enter to send)"
            }
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isAnswering}
          />
          <div className="flex items-center justify-between">
            {/* Mode toggle */}
            <div className="flex gap-1">
              {(["auto", "steering", "qa"] as MessageMode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className="rounded-full px-2 py-0.5 text-xs capitalize"
                  style={{
                    backgroundColor:
                      mode === m
                        ? "var(--md-sys-color-secondary-container)"
                        : "transparent",
                    color:
                      mode === m
                        ? "var(--md-sys-color-on-secondary-container)"
                        : "var(--md-sys-color-on-surface-variant)",
                    border: "1px solid var(--md-sys-color-outline-variant)",
                  }}
                >
                  {m === "auto"
                    ? `auto · ${effectiveMode}`
                    : m}
                </button>
              ))}
            </div>
            {/* Send button */}
            <button
              type="button"
              onClick={() => void handleSend()}
              disabled={!input.trim() || isAnswering}
              className="rounded-full px-3 py-1 text-xs font-medium disabled:opacity-40"
              style={{
                backgroundColor: "var(--md-sys-color-primary)",
                color: "var(--md-sys-color-on-primary)",
              }}
            >
              {isAnswering ? "Answering…" : "Send"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ai-coscientist-app/frontend && bun run check 2>&1 | tail -10
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd ai-coscientist-app && git add frontend/src/workbench/components/tabs/ChatTab.tsx
git commit -m "feat: add ChatTab component with unified feed and input"
```

---

## Task 7: Wire ChatTab into RunDetail

**Files:**
- Modify: `ai-coscientist-app/frontend/src/workbench/pages/RunDetail.tsx`

- [ ] **Step 1: Add `"chat"` to TABS, icon map, and render the tab**

In `RunDetail.tsx`, make these three edits:

**Edit 1** — `TABS` constant (line 36):

```typescript
// Replace:
const TABS = ["overview", "ideas", "evidence", "tournament", "report"] as const;
type TabName = (typeof TABS)[number];
// With:
const TABS = ["overview", "ideas", "evidence", "tournament", "report", "chat"] as const;
type TabName = (typeof TABS)[number];
```

**Edit 2** — `TAB_ICON_NAMES` (add the `chat` entry):

```typescript
// Replace:
const TAB_ICON_NAMES: Record<TabName, string> = {
  overview: "monitoring",
  ideas: "format_list_numbered",
  evidence: "menu_book",
  tournament: "compare_arrows",
  report: "description",
};
// With:
const TAB_ICON_NAMES: Record<TabName, string> = {
  overview: "monitoring",
  ideas: "format_list_numbered",
  evidence: "menu_book",
  tournament: "compare_arrows",
  report: "description",
  chat: "chat",
};
```

**Edit 3** — Add the `ChatTab` import at the top with the other tab imports:

```typescript
import { ChatTab } from "../components/tabs/ChatTab";
```

**Edit 4** — Add `ChatTab` render inside the `{!loaded && !error ? ... : <div ...>}` block, after the `report` block (line 305):

```tsx
          {activeTab === "chat" && <ChatTab run={run} />}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ai-coscientist-app/frontend && bun run check 2>&1 | tail -10
```

Expected: no errors

- [ ] **Step 3: Verify the tab appears in the browser**

```bash
cd ai-coscientist-app && make dev
```

Navigate to any run and confirm a "Chat" tab appears. Open it and verify the empty state message renders.

- [ ] **Step 4: Commit**

```bash
cd ai-coscientist-app && git add frontend/src/workbench/pages/RunDetail.tsx
git commit -m "feat: wire ChatTab as sixth tab in RunDetail"
```

---

## Task 8: End-to-end verification

- [ ] **Step 1: Run full backend test suite**

```bash
cd ai-coscientist-app && pytest --tb=short -q
```

Expected: all tests pass

- [ ] **Step 2: Run a mock run and verify the Chat tab**

```bash
cd ai-coscientist-app && make dev
```

1. Open http://localhost:5173, create a new run with any research goal.
2. Switch to the Chat tab immediately after starting.
3. Verify milestone rows appear as the run progresses (supervisor, generate, ranking, etc.).
4. While the run is active, type a steering message (e.g., "focus on cytokines") and send — verify the "Steering · pending" badge appears.
5. After the run completes, open the messages endpoint directly: `curl http://localhost:8008/api/runs/{id}/messages` — verify the steering message now has `"applied": true`.
6. Reload the page, switch to Chat tab — verify messages rehydrate from the server.

- [ ] **Step 3: Commit final state**

```bash
cd ai-coscientist-app && git add -A
git commit -m "feat: interaction model — chat tab, steering injection, milestone messages, Q&A"
```
