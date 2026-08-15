# Streaming interview prose, with the run spec as a trailing block

Date: 2026-08-15
Status: approved, not yet implemented

## Problem

The goal interview returns one JSON object per turn. `assistant_message` is a
string field inside it, alongside the five structured fields and `completed`
(`interviews_prompts._RESPONSE_SCHEMA`).

Three consequences follow, and only the first is obvious.

**The prose cannot stream.** `interviews_model._collect_stream_content` says so
outright: content deltas are "accumulated silently: they are fragments of the
response JSON, never prose to show a scientist." The scientist watches the
chain of thought arrive live and then waits for the answer to appear whole.
Every other chat product they use streams the answer itself.

**The prose cannot be rich.** A markdown document inside a JSON string is an
escaping exercise, so the system prompt asks for "exactly one concise,
context-sensitive question" and gets back a single line. The interview is the
first surface a scientist talks to and it reads markedly poorer than the
assistants they are used to.

**Nothing renders markdown anyway.** `chat_timeline_bubble_text.tsx` renders
`{content}` into a plain `<span>`, and the frontend has no markdown library
among its four runtime dependencies. This is the part that is *not* interview-
specific: `qa.py` already streams raw prose as `{"type": "chunk", ...}` frames
with no JSON envelope, so in-run Q&A can already emit markdown today — and it
renders as literal asterisks.

## What the conventions actually are

Two questions were researched separately, because they have different answers.

**Is prose a text stream or a JSON field?** Settled and universal: a text
stream. General guidance on structured outputs is explicit that the JSON is
not the user-visible channel — you stream conversational text to the user and
keep the machine-readable part separate. This is the convention this codebase
violates, and it is the whole of the reported problem.

**How does the structured part ride along?** Genuinely split, by purpose:

| Product | Mechanism | Shape |
|---|---|---|
| Claude | inline tag | `<antArtifact identifier= type= title=>...</antArtifact>` in the message stream, extracted by the frontend |
| ChatGPT | tool call | `canmore.create_textdoc({name, type, content})`, out-of-band from the prose |
| Vercel AI SDK | tool call | generative UI renders components from tool results |

The streaming-implementation consensus is worth recording because it dictates
the ordering below: tags mark the boundary, and the JSON is parsed once the
closing tag arrives, rather than parsed incrementally mid-flight.

## Decision: an inline trailing block

The inline-tag shape, for reasons specific to this deployment rather than
because it is more popular:

- **No new provider surface.** Tool calling would add a second capability axis
  next to the `json_schema` / `json_object` shim already in
  `_interview_request`, plus streaming tool-call argument assembly.
- **DeepSeek + thinking + streaming tool calls is unquantified risk.** DeepSeek
  supports tool use in thinking mode from V3.2, but streamed tool-call
  arguments arrive as fragments that must be buffered, and third-party reports
  claim V4 rejects a follow-up with 400 unless `reasoning_content` is
  round-tripped on assistant messages carrying tool calls. DeepSeek's official
  tool-calls page neither confirms nor denies it. The repo's existing scars
  (`THINKING_FLOOR_MAX_TOKENS`, `thinking_safe_timeout`) are all cases where a
  thinking-mode interaction failed silently and only in production; this is the
  first surface a scientist touches.
- **It degrades better than what exists.** See Failure modes below.

Rejected: **tool calling** (above) and **two passes** — streaming prose from one
call and extracting fields with a second doubles per-turn latency on the most
latency-visible surface, and lets the two calls disagree about what was decided.

## Wire format

The model writes markdown prose, then closes the turn with one block:

```
Got it — cardiac fibroblasts it is. A couple of things worth pinning down:

- **Model system** — primary human cells, or an iPSC-derived line?
- **Readout** — are you measuring collagen deposition directly?

<run_spec>
{"research_challenge": "...", "focus_area": ["..."], "preferences": [],
 "lab_constraints": [], "title": "...", "completed": false}
</run_spec>
```

Prose is everything before the opening marker. Content after the closing marker
is ignored. The state block comes **last**, which is what makes streaming
possible; it costs nothing, because a thinking model has already reasoned in
`reasoning_content` before emitting its first content token.

The tradeoff this accepts: the model commits to its prose before writing the
fields, so it cannot decide in JSON and then narrate the decision.

## Components

### `app/app/interviews_wire.py` (new)

Owns the format and nothing else:

- The marker constants.
- `split_prose_and_spec(text) -> (prose, fields | None)` — pure, for a complete
  response.
- An incremental splitter fed one delta at a time, returning prose safe to emit
  and buffering the rest. It holds back up to `len(OPEN_MARKER) - 1` trailing
  characters so a marker straddling a chunk boundary (`"<run_"` then `"spec>"`)
  is never emitted as prose and then retracted.

A separate module keeps `interviews_model.py` and `interviews_prompts.py` under
the 500-line ceiling and gives the splitter a seam-free home to be unit-tested
directly.

### `app/app/interviews_model.py`

`_collect_stream_content` gains a prose sink alongside its reasoning sink, and
feeds content deltas through the splitter instead of accumulating them
silently. `_call_interview_model` returns **the same dict shape it returns
today** (`assistant_message`, the five fields, `completed`), so
`_resolved_turn`, persistence, the deterministic fallback, and every test that
monkeypatches `interviews._call_interview_model` are untouched.

### `app/app/interviews_prompts.py`

`_RESPONSE_SCHEMA` and the `response_format` plumbing are removed:
`_interview_request` returns `(model, messages)` with no response format, which
deletes the `_json_schema_turn` / `_json_object_turn` capability branch and its
dependency on `co_scientist.llm_request._supports_json_schema_response_format`.
Little is lost — production runs DeepSeek in `json_object` mode, which never
enforced the schema.

The system prompt is rewritten to ask for markdown prose and to require the
trailing block, and its "exactly one concise question" instruction is relaxed
so answers may use short paragraphs, lists, and emphasis where they help. It
must still ask one question at a time; brevity of *questioning* is the point,
not brevity of formatting.

### `app/app/interviews_stream.py`

Emits `{"type": "chunk", "content": ...}` as prose arrives — deliberately the
same frame name `qa.py` already emits, so the frontend has one streaming
contract for both chat surfaces. The terminal `{"type": "interview", ...}`
frame is unchanged.

### Frontend

`react-markdown` + `remark-gfm` as new runtime dependencies, wrapped in a
single `MarkdownMessage` component so no other component imports them
directly. Chosen over a hand-rolled renderer because this renders model output,
where markdown edge cases are endless and a hand-rolled parser is an XSS
surface; `react-markdown` does not use `dangerouslySetInnerHTML`.

Assistant bubbles render markdown. **User bubbles stay a plain text span** —
they carry user input, not model output, and the collapse-past-four-lines
measurement in `chat_timeline_bubble_text.tsx` depends on that span's text
metrics.

The chat session hook appends `chunk` frames into a live assistant bubble, with
a ~50ms render debounce rather than re-rendering per token.

## Failure modes

Strictly better than the current behavior, which is the second reason for this
shape. Today any malformed response raises `HTTPException(503)` from
`_call_interview_model` and discards the turn into the deterministic fallback.

| Condition | Behavior |
|---|---|
| No `<run_spec>` block | Keep the prose; carry previous fields forward; `completed` stays false; log a warning |
| Malformed JSON inside the block | Same |
| Turn truncated mid-block | Same |
| Prose empty (block only, or nothing at all) | Unchanged — `_resolved_turn` still raises 502, "Agent returned no message" |
| Provider absent or erroring | Unchanged — the existing deterministic fallback turn |

Carrying fields forward is safe because the fields are cumulative interview
state, not a per-turn derivation: an unchanged field means the turn learned
nothing new about it, which is exactly what a missing block means.

Carry-forward happens inside `_call_interview_model`, which has the interview
row in hand: when no block parses, it returns the previous fields in the dict
it already returns, so `_normalized_fields` downstream sees them unchanged and
no caller learns that anything was missing. The empty-prose 502 is retained
deliberately — a turn with nothing to show the scientist is a broken turn under
either format, and it is now a *newly reachable* shape, since the old schema at
least declared `assistant_message` as `minLength: 1`.

## Testing

- **Splitter units** (`interviews_wire`): marker split across two and three
  deltas; no marker at all; marker present but JSON malformed; prose that
  legitimately contains the literal marker text; empty prose with only a block.
- **Turn integration**: a streamed turn emits `chunk` frames before the
  terminal `interview` frame, and the persisted turn's content is the prose
  only, with no marker text in it.
- **Field carry-forward**: a turn whose response omits the block leaves the
  previously derived fields intact and does not 503.
- **Frontend**: an assistant bubble renders markdown structure; a user bubble
  with the same content renders it literally and stays collapsible.

## Out of scope

- The Q&A backend (`qa.py`) — it already streams prose correctly and gains the
  renderer for free.
- The run spec card and the run detail surfaces.
- The engine's own structured-output paths, which are machine-to-machine and
  have no prose channel.
