"""The interview's provider call and its deterministic recovery path."""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from co_scientist.llm import coerce_json_list
from fastapi import HTTPException
from pydantic import BaseModel, Field

import app.credentials as credentials
import app.offline_guard as offline_guard
import app.store as store
from app.config import (
    CONVERSATIONAL_REASONING_EFFORT,
    THINKING_FLOOR_TIMEOUT_SECONDS,
    deepseek_thinking_kwargs,
    settings,
    thinking_off_kwargs,
    thinking_safe_max_tokens,
)
from app.llm_scope import budgeted, stream_chunks

logger = logging.getLogger(__name__)

OPEN_MARKER = "<run_spec>"
CLOSE_MARKER = "</run_spec>"


def _parse_spec_body(body: str) -> dict[str, Any] | None:
    """Parse a spec block's body, or None when it is not a JSON object.

    Args:
        body: The text between the open and close markers.

    Returns:
        The parsed object, or None when the body is malformed or is valid
        JSON of some other type (a list, a bare string).
    """
    try:
        parsed = json.loads(body)
    except ValueError:
        logger.warning("Interview spec block is not valid JSON")
        return None
    if not isinstance(parsed, dict):
        logger.warning("Interview spec block is not a JSON object")
        return None
    return {str(key): value for key, value in parsed.items()}


def _held_back_length(buffer: str) -> int:
    """Return how many trailing characters might begin the opening marker.

    A marker split across two deltas (``"<run_"`` then ``"spec>"``) would be
    relayed as prose and then have to be retracted, so any suffix that could
    still grow into the marker is withheld until the next delta resolves it.

    Args:
        buffer: Prose accumulated so far and known to contain no whole
            marker.

    Returns:
        The length of the longest suffix of ``buffer`` that is a proper
        prefix of :data:`OPEN_MARKER`, and so must be held back.
    """
    longest = min(len(buffer), len(OPEN_MARKER) - 1)
    for size in range(longest, 0, -1):
        if buffer.endswith(OPEN_MARKER[:size]):
            return size
    return 0


class TurnSplitter:
    """Splits a streamed turn into prose to relay and a spec block to parse.

    Deltas go in one at a time; prose safe to show the scientist comes back
    immediately, and everything from the opening marker onward accumulates
    for parsing once the turn ends. Call :meth:`finish` to flush the last
    held-back prose and read the result.
    """

    def __init__(self) -> None:
        """Start a splitter for one turn; splitters are not reusable."""
        # Prose whose tail might still turn out to open the spec block.
        self._pending = ""
        # Spec-block text collected once the opening marker was seen.
        self._spec: list[str] = []
        self._in_spec = False
        # Prose already released, kept so finish() can return the whole turn.
        self._prose: list[str] = []

    def feed(self, delta: str) -> str:
        """Consume one content delta and return prose safe to relay.

        Args:
            delta: The next content fragment from the stream.

        Returns:
            Prose to show the scientist, possibly empty when the whole
            delta was held back or belongs to the spec block.
        """
        if self._in_spec:
            self._spec.append(delta)
            return ""
        buffer = self._pending + delta
        start = buffer.find(OPEN_MARKER)
        if start != -1:
            self._in_spec = True
            self._pending = ""
            self._spec.append(buffer[start + len(OPEN_MARKER) :])
            return self._release(buffer[:start])
        held = _held_back_length(buffer)
        self._pending = buffer[len(buffer) - held :] if held else ""
        return self._release(buffer[: len(buffer) - held])

    def _release(self, prose: str) -> str:
        """Record and return prose being relayed to the scientist."""
        if prose:
            self._prose.append(prose)
        return prose

    def finish(self) -> tuple[str, str, dict[str, Any] | None]:
        """Flush held-back prose and return the turn's resolved parts.

        Returns:
            A ``(trailing_prose, whole_prose, fields)`` triple.
            ``trailing_prose`` is the remainder that was still held back and
            has not been relayed yet, so a caller streaming to a scientist
            can emit it as the turn's last fragment. ``fields`` is None when
            the turn carried no parseable spec block.
        """
        trailing = self._release(self._pending)
        self._pending = ""
        whole = "".join(self._prose).strip()
        if not self._in_spec:
            return trailing, whole, None
        body = "".join(self._spec)
        end = body.find(CLOSE_MARKER)
        return (
            trailing,
            whole,
            _parse_spec_body(body if end == -1 else body[:end]),
        )


class CreateInterviewRequest(BaseModel):
    """Initial scientist challenge for a new interview.

    ``document_ids`` names documents already staged through
    ``/api/documents``. They are attached to the interview, so the very
    first turn is scoped with the scientist's own material rather than
    reaching the work only after the plan is fixed.
    """

    research_challenge: str = Field(..., min_length=1, max_length=20_000)
    document_ids: list[str] = Field(default_factory=list)


class InterviewTurnRequest(BaseModel):
    """One scientist answer or correction, with any newly attached documents."""

    content: str = Field(..., min_length=1, max_length=20_000)
    document_ids: list[str] = Field(default_factory=list)


class InterviewFieldsRequest(BaseModel):
    """Scientist-authored edits to the five structured fields.

    ``lab_constraints`` (K5) defaults to empty so clients that predate
    the field keep validating; omitting it records "no constraints".
    """

    research_challenge: str = Field(..., min_length=1, max_length=20_000)
    focus_area: list[str]
    preferences: list[str]
    lab_constraints: list[str] = Field(default_factory=list)
    title: str | None = Field(None, max_length=200)


# The turn's shape, restated for the model. The five fields are unchanged
# from the JSON-object format this replaced; what changed is where they
# live -- a trailing block, after prose that is now ordinary markdown rather
# than a string inside a JSON document. ``lab_constraints`` (K5) is optional:
# the scientist may legitimately have none, the field is elicited when
# relevant rather than on a fixed schedule, and normalization defaults an
# omission to the empty list.
_FORMAT_PROMPT = (
    "Write your reply to the scientist as ordinary markdown. Then, on its "
    "own line after the reply, emit exactly one block:\n\n"
    f"{OPEN_MARKER}\n"
    '{"research_challenge": "...", "focus_area": ["..."], '
    '"preferences": ["..."], "lab_constraints": ["..."], '
    '"title": "..." or null, "completed": true or false, '
    '"questions": [...]}\n'
    f"{CLOSE_MARKER}\n\n"
    "Rules for the block:\n"
    "- It MUST be the last thing in your reply, and MUST appear exactly "
    "once. Never open it before you have finished writing to the "
    "scientist.\n"
    "- The five fields carry the interview's whole current state, not just "
    "what this turn changed. Repeat fields that did not change.\n"
    "- ``questions`` is the exception: it describes only the question THIS "
    "turn is asking. Never repeat a previous turn's questions, and omit "
    "the key only on the completing turn, which asks nothing.\n"
    "- It is machine-read and never shown to the scientist, so never "
    "mention it, and never refer to it in your reply.\n"
    "- Its contents MUST be valid JSON. Do not wrap it in a code fence."
)

# The clickable half of a turn's question. The scientist can always type
# instead, so this never changes what the prose has to say -- it only saves
# them writing out an answer the model could already enumerate.
_QUESTIONS_PROMPT = r"""
## Offering answers to click

Every question you ask reaches the scientist twice: as prose, and as
clickable answers in the block's ``questions`` array. Whenever your reply
ends on a question, that array carries it -- there is no turn that asks in
prose alone:

[{"header": "Model system", "question": "Which model system should the
ideas be built around?", "multi_select": false, "options": [{"label":
"Primary human cells", "description": "Closest to patient biology"},
{"label": "iPSC-derived line", "description": "Renewable and editable"}]}]

- ``header`` is a two-or-three word label for what is being chosen.
  ``question`` is the question itself, in full. ``options`` carries two to
  five answers, each a short ``label`` and a one-line ``description`` of
  what choosing it would mean for the work.
- Set ``multi_select`` true when several answers can hold at once (which
  focus areas to prioritize, which exclusions apply) and false when they
  are alternatives (which model system, which readout).
- Usually one question, matching the one question your prose asks. Offer
  two or three only when one decision genuinely has separate facets the
  scientist would settle together.
- An open answer space is not a reason to omit the array. Where you cannot
  enumerate the answers, enumerate the *readings*: the two to four
  directions the answer could plausibly take, each as an option a scientist
  could click and then refine. The click is a starting point, not a
  commitment -- they can always write something else instead.
- Do NOT enumerate the options again in your prose. They are shown to the
  scientist as buttons under your reply, so listing them as well says
  everything twice. Your prose asks the question and gives the context
  that makes the choice meaningful; the options are the answers to it.
- The scientist can always ignore the options and write their own answer,
  so the question in your prose must stand on its own.
- The completing turn is the one turn that omits ``questions``: it asks
  nothing, so there is nothing to offer.
"""

# Rebased on Google's own two prompts for this product family (captured
# 2026-06 under references/ui-ux/, since deleted -- read them out of git
# history): the Gemini Enterprise chat system prompt supplies the
# voice and formatting rules and the multi-turn block, and Idea Generation's
# config-generation prompt -- the structural twin of this interview, which
# also turns a chat into a machine-read block -- supplies the derivation
# guidance, the self-critique pass, the singular-goal rule, and the edge
# cases. Both are shipped Google prompts for the surfaces this one imitates,
# so they are the baseline rather than something to invent past.
#
# What was deliberately not carried over: emoji on headings (Gemini
# Enterprise itself excludes serious topics, which is most research goals);
# mirroring slang, narrowed here to matching the scientist's register;
# Idea Generation's NO-CONFIG sentinel, since this wire format carries the
# whole state every turn rather than suppressing it (see _FORMAT_PROMPT);
# and its extra Config fields -- reviewer instructions, stratification
# attributes, and model-derived safety flags -- which would be a schema and
# backend change, not a prompt change. This app screens safety separately
# (app.safety, app.hypothesis.safety) and its reviewer prompts are fixed.
_GUIDE = r"""# Role

You are the Agent conducting Google Hypothesis Generation's research-goal
interview. You work with one scientist to scope exactly one scientific
research goal, which a multi-agent system then explores on its own. Derive
only information the scientist supplied; never invent laboratory
capabilities, data, constraints, or preferences.

# Interview instructions

- ALWAYS answer in the same language as the scientist.
- ALWAYS use markdown. Use several paragraphs to bring clarity, and prefer
  the richer markdown features -- headings, tables, and the '---'
  separator -- over one unbroken run of prose. Start a section with a '## '
  heading when a reply has distinct parts, and separate those sections
  with a '---' horizontal rule.
- Prefer a table over a list whenever what you are laying out shares the
  same criteria: candidate mechanisms against what would distinguish them,
  model systems against what each one buys, scoping options against what
  each includes and excludes. Use a list only when the items are not
  comparable along shared criteria, and give every item a bold label.
- Bold the scientific terms, mechanisms, and options under discussion.
- Markdown escaping (critical): escape special markdown characters that
  appear inside content. Gene, variant, construct, cell-line and file
  names carry characters like |, *, _, #, [ and ] that markdown would
  otherwise consume -- write BRCA1\_variant, not BRCA1_variant. An
  unescaped | inside a table cell breaks the table.
- Keep the data in a table cohesive: cells in the same column hold the
  same kind of thing, written in the same style.
- Do not over-explain, and never say the same thing twice in one reply.
  Assume the scientist knows their own field: explain what needs
  explaining and no more.
- Make sure no block of text is too long or too dense to read.
- Mirror the scientist's register. Match their level of technical detail
  and their vocabulary: field shorthand if they write in it, plain
  language if they do not.
- Write in the first person about what you understood and what you can
  help with. You are a knowledgeable colleague thinking alongside a
  scientist, not a form: say what you understood, say what it implies or
  what it rules out, and then ask.
- ALWAYS invite the conversation forward. Every turn but the completing
  one ends on a question -- and every question you ask is also carried as
  clickable answers in the block (see "Offering answers to click"), so the
  scientist can click one instead of writing it out.
- Use no emoji. These goals routinely concern disease, mortality and human
  subjects, where decoration reads as tone deaf.

# Turn taking

Ask about one thing at a time. That governs how many *questions* a turn
asks -- exactly one -- and never how much you may explain before asking
it. A turn that reflects the goal back, lays out the distinctions that
matter, and closes on a single question is correct and is what this
interview should read like; a bare one-line question is not. Do not pad
with filler or restate the scientist's own words back at them as though
they were your finding, but never strip a reply to one sentence when there
is substance to give.

Where the scientist's wording is ambiguous, ask about the ambiguity rather
than guessing past it. Where you cannot give a concrete answer to
something they ask, say so and name the ways they could find it.

# Multi-turn conversation

- Review first: before writing a reply, review the entire conversation to
  establish full context.
- Leverage history: do not treat a turn as a standalone query. Actively
  integrate the facts, decisions and preferences already established.
- Ensure consistency: a reply must never contradict the conversation. If
  what the scientist has just said conflicts with something established
  earlier, ask about the conflict rather than silently choosing one.
- Stay grounded: every reply is a direct continuation of this
  conversation, specific to its cumulative context. Avoid generic,
  abstract answers.

# The five fields

Maintain exactly five structured fields.

1. Research Challenge: the precise scientific question or hypothesis.
2. Focus Area: scientific subareas or mechanisms to prioritize.
3. Preferences: what makes an idea good for this goal -- exclusions, the
   novelty boundary, feasibility requirements, the models or data ideas
   should be built around, and the desired depth of output.
4. Lab Constraints: the scientist's own laboratory constraints that
   proposed experiments must respect -- equipment and instrumentation,
   model systems or organisms they can work with, budget, and personnel
   capabilities. Elicit these alongside the other fields when relevant; an
   explicit statement that there are none leaves the list empty. Never
   infer lab capabilities the scientist has not stated.
5. Title: an optional concise title.

# Deriving good field values

Scoping is an adaptive process. Propose values, then critically evaluate
your own proposal before committing it: do the challenge, the focus areas
and the preferences capture every nuance of what the scientist said? Did
you consider the less obvious readings? Revise before you emit the block.
Use self-feedback.

- Understand the *why* behind the goal. What problem is the scientist
  actually facing, and what are their unstated needs? Explore the
  different possible interpretations of what they want, including the less
  obvious ones, and ask about whichever one would most change the work.
- The research challenge is a concrete, actionable statement carrying the
  intended scientific impact, not a restatement of what the scientist
  typed. Consider it at several levels of abstraction and keep the best.
- State the research challenge in the singular. If the scientist asks for
  several hypotheses or directions, the challenge is still one question --
  the system generates many competing ideas against it.
- For preferences, take the scientist's own point of view: what would an
  ideal result look like to them, and what concrete requirement does that
  translate into? Prefer several simple, independent preferences over one
  compound one. Include the implicit and derived constraints that follow
  from the goal, not only those said out loud -- while never inventing a
  capability or a restriction they have not implied.
- Every value must be explicit and assume no implicit concepts. Later
  agents read these fields without the conversation around them.
- Capture everything the scientist supplied somewhere in the fields. When
  it is unclear which field something belongs in, put it in preferences --
  except for what the scientist can and cannot do in their own laboratory,
  which must reach Lab Constraints. A preference may refer to the same
  model system or dataset; Lab Constraints is where the run reads what the
  lab actually has, so an omission there is the one that costs.

# Attached documents

When ``attached_documents`` is present, the scientist has attached those
documents to this conversation. Read them, scope the goal against what
they actually say, and ask questions that build on them rather than
re-asking what they already answer. An excerpt marked as truncated is
partial; do not treat it as the whole document.

# Edge cases

- Small talk, or a question about you, this system, or the scientist's own
  group: answer it, then guide the conversation back to scoping the goal.
  Carry every field forward unchanged and leave completed false.
- An empty or contentless turn: say plainly that you need something to
  work with and repeat the one question you are waiting on. Carry every
  field forward unchanged.
- Approval carrying no new information ("looks good", "that's better"):
  do not read it as new scope. Ask whether anything else should change
  before the run starts, or complete if everything essential is captured.
- A turn that only corrects one field: change that field alone and leave
  every other field exactly as it was.

# Completion

Continue until the challenge is precise, at least one focus area is known,
and meaningful preferences -- or an explicit statement that there are none
-- have been captured. Then complete, on that turn.

Completing is the point of this interview, not a fallback: the scientist
came to start a run. Neither of the products this interview is modelled on
has to make this judgement -- one is open-ended chat and the other waits
for a button -- so it is stated here explicitly. Ask a further question
only when a different answer would change the research goal the system
explores.

Experimental design detail does not meet that bar. Sample provenance and
pairing, assay and platform choice, cohort size, timelines, and
statistical power shape how the scientist would run the work; they do not
change which mechanisms are worth exploring. Neither does a distinction
you have already recorded in the fields. Record what you know and move on.

By your fourth turn, complete with what you have unless something
essential is genuinely missing -- and complete earlier when the essentials
arrive earlier.

On the completing turn, write a short closing message: what you took the
scientist to be asking for, in a sentence or two of your own words, and
then that the run can be started or the scope refined further. Set
completed to true and ask no further question.

Do not restate the scope field by field. The workbench renders the fields
you emit below as an editable plan document directly beneath this message,
so a structured summary here is the same content twice on one screen --
which is exactly how it read before this instruction replaced one asking
for that summary. Say what the fields do not: why this is the shape you
settled on, or what you deliberately left out.

# Output format

"""

_SYSTEM_PROMPT = f"{_GUIDE}{_FORMAT_PROMPT}\n{_QUESTIONS_PROMPT}"


def _clean_list(raw: Any) -> list[str]:
    """Normalize a model- or user-produced list into non-empty strings.

    The interview turn carries no schema (a plain trailing JSON block), so
    a single item can plausibly arrive as a bare string rather than
    wrapped in a one-element list; ``coerce_json_list`` recovers that
    shape rather than silently stranding the interview on a real answer.
    """
    result: list[str] = coerce_json_list(
        raw, element="str", site="interviews.field_list"
    )
    return result


def _normalized_fields(response: dict[str, Any]) -> dict[str, Any]:
    """Normalize the model response into the verified five-field contract.

    ``lab_constraints`` (K5) defaults to the empty list when the model
    omits it: the scientist may have none, and older turns of an in-flight
    interview predate the field entirely.
    """
    title = response.get("title")
    return {
        "research_challenge": str(
            response.get("research_challenge") or ""
        ).strip(),
        "focus_area": _clean_list(response.get("focus_area")),
        "preferences": _clean_list(response.get("preferences")),
        "lab_constraints": _clean_list(response.get("lab_constraints")),
        "title": str(title).strip() if title else None,
    }


def _essentials_ready(fields: dict[str, Any]) -> bool:
    """Whether the essential scoping fields (challenge + focus) are present.

    Preferences are intentionally excluded: the interview contract treats an
    explicit "no constraints" as a valid terminal state (see the system
    prompt), so an empty preferences list must not block a model-confirmed
    completion. Used to validate the model's own ``completed`` signal.
    """
    return bool(fields["research_challenge"] and fields["focus_area"])


def _ready(fields: dict[str, Any]) -> bool:
    """Return whether required scoping fields contain substantive values.

    Requires preferences as well, so the deterministic recovery path (which
    fills fields from scientist answers in order) collects a preferences answer
    before it completes, rather than finalizing after the focus-area answer.
    """
    return bool(
        fields["research_challenge"]
        and fields["focus_area"]
        and fields["preferences"]
    )


def _transcript_turn(turn: dict[str, Any]) -> dict[str, Any]:
    """Render one transcript turn, carrying its reasoning when stored.

    A chat's turns are few and short, so the Agent's own chain of thought
    stays in the context it is asked to continue from -- the next question
    follows from the reasoning as much as from the message it produced.
    """
    entry = {"role": turn["role"], "content": turn["content"]}
    reasoning = str(turn.get("reasoning") or "").strip()
    if reasoning:
        entry["reasoning"] = reasoning
    return entry


def _attached_documents(interview: dict[str, Any]) -> list[dict[str, str]]:
    """Return excerpts of the documents attached to this interview.

    The upload used to be possible only after the run existed, which put
    the scientist's own material behind the plan it was supposed to shape.
    Reading it here is what makes the attachment do what the composer's
    paperclip implies. Empty for an interview with none, and for the
    synthetic rows the prompt builders are exercised with directly.
    """
    interview_id = interview.get("id")
    if not interview_id:
        return []
    return store.interview_document_excerpts(str(interview_id))


def _prompt(interview: dict[str, Any]) -> str:
    """Render the persisted transcript and current derivation for the model."""
    transcript = [_transcript_turn(turn) for turn in interview["turns"]]
    context: dict[str, Any] = {
        "current_fields": interview["fields"],
        "transcript": transcript,
    }
    attached = _attached_documents(interview)
    if attached:
        context["attached_documents"] = attached
    return json.dumps(context, ensure_ascii=False)


def _interview_request(interview: dict[str, Any]) -> tuple[str, Any]:
    """Build the model and messages for one Agent turn.

    The turn carries no ``response_format`` at all. It used to: a
    ``json_schema`` request for providers that support it and a
    ``json_object`` downgrade (with the schema restated in the prompt) for
    those that do not. Both are gone with the JSON envelope they enforced --
    the answer is now prose plus a trailing block, which no provider-side
    format can describe. Little was lost with the branch: production runs
    DeepSeek, which only ever got the ``json_object`` downgrade, and that
    mode constrains the response to *some* JSON object, never to this
    schema.

    Args:
        interview: The durable interview row being advanced.

    Returns:
        A ``(model, messages)`` pair ready for litellm.
    """
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _prompt(interview)},
    ]
    return settings.effective_chat_model, messages


# Receives each chain-of-thought fragment as the model emits it.
ReasoningSink = Callable[[str], Awaitable[None]]
# Receives each fragment of the answer's prose as the model writes it.
ProseSink = Callable[[str], Awaitable[None]]


@dataclasses.dataclass(frozen=True)
class TurnSinks:
    """Where one streamed turn's two live channels are relayed.

    Both are optional: a caller that only wants the resolved turn (the
    non-streaming ``POST`` path, and every test that drives a turn directly)
    passes neither and receives the same result.
    """

    on_reasoning: ReasoningSink | None = None
    on_prose: ProseSink | None = None


# Silence, not duration, is what marks an interview turn as lost. The turn
# streams and its chain of thought is relayed to the scientist as it arrives,
# so a long reasoning pass is visible progress, not a blank wait -- while a
# provider that has stopped answering goes quiet immediately. Bounding the
# total instead is what made a funded chain of thought fail the turn on the
# clock right after it stopped failing on the token budget.
_INTERVIEW_STALL_SECONDS = 45.0
# Derived so the clock cannot drift below the token budget it has to admit,
# plus room for the prompt round-trip either side of the reasoning.
_INTERVIEW_TOTAL_SECONDS = THINKING_FLOOR_TIMEOUT_SECONDS + 60.0

# What one turn's answer is given, before the thinking floor raises it.
#
# Thinking spends reasoning tokens against the same budget, so on a model
# that reasons this is what remains for the prose and its spec block once
# the floor has covered the chain of thought (see thinking_safe_max_tokens);
# on a model that does not, it is the whole turn. Sizing it for the answer
# alone is what leaves a run untitled and an interview turn blank.
#
# 3k -> 4k when the block learned to carry clickable answers (a turn
# offering three options writes a label and a description for each on top
# of the five fields it restates every turn). 4k -> 6k once the block
# became mandatory on every question-asking turn: the guide asks for
# several paragraphs and often a table before the block is even opened,
# and the block is last, so a tight ceiling eats exactly it -- losing the
# whole turn's state, not just the options. A ceiling is not a
# reservation, so the headroom costs nothing on the turns that fit.
_ANSWER_MAX_TOKENS = 6_000

# Relayed through the reasoning sink when a turn that spent its whole reply
# thinking is retried -- so the scientist watching the chain of thought
# sees the model start over instead of the turn simply going quiet before
# the 502 that used to follow (see _resolved_turn in app.interviews).
_THINKING_ONLY_RETRY_NOTE = (
    "\n\n[Answered nothing after reasoning at length; retrying without "
    "extended thinking.]\n\n"
)


async def _stream_interview_content(
    interview: dict[str, Any], sinks: TurnSinks
) -> tuple[str, dict[str, Any] | None]:
    """Stream one Agent turn, relaying it live, and return what it resolved to.

    The call always streams so there is a single transport to reason about.
    DeepSeek emits the whole chain of thought as ``reasoning_content`` deltas
    before the first ``content`` delta, so reasoning surfaces live while the
    answer is still being written. Content deltas are the answer's prose and
    are relayed as they arrive, up to the trailing spec block, which is
    withheld and parsed at the end (see ``app.interviews.model``).

    A turn that spends its whole reply reasoning and writes no answer at
    all is not a provider failure -- the stream ends clean, just empty --
    so it is retried once with thinking off rather than surfacing as one;
    see ``_run_interview_completion``.

    Returns:
        The turn's whole prose and its parsed fields, the latter None when
        the turn carried no usable spec block.
    """
    # Refuse before the request is shaped, not after: the prompt carries the
    # scientist's research goal verbatim, and forced offline means it does
    # not leave the process. The raise lands in _call_interview_model's
    # except branch, which is the same 503 -> scripted-turn path an absent
    # provider already takes.
    offline_guard.require_remote_chat("the interview")
    model, messages = _interview_request(interview)
    # A scoped bring-your-own-key credential overrides both the model and
    # the deployment credential for this turn.
    model, api_key = credentials.byok_model_and_key(model)
    prose, fields, reasoned = await _run_interview_completion(
        model, messages, api_key, sinks, thinking_enabled=True
    )
    if prose.strip() or not reasoned:
        return prose, fields
    logger.warning(
        "Interview turn reasoned and wrote no answer; retrying once with "
        "thinking off"
    )
    await _emit(sinks.on_reasoning, _THINKING_ONLY_RETRY_NOTE)
    prose, fields, _ = await _run_interview_completion(
        model, messages, api_key, sinks, thinking_enabled=False
    )
    return prose, fields


async def _run_interview_completion(
    model: str,
    messages: Any,
    api_key: str | None,
    sinks: TurnSinks,
    *,
    thinking_enabled: bool,
) -> tuple[str, dict[str, Any] | None, bool]:
    """Stream one completion request and drain it.

    Split out of ``_stream_interview_content`` so the thinking-only retry
    is a second call to this, not a second copy of the request.

    Returns:
        The turn's prose, its parsed fields, and whether the model emitted
        any reasoning at all -- the caller uses the last to tell a
        thinking-only turn from one that simply answered with nothing to
        say.
    """
    import app.llm_request as llm_request

    thinking_kwargs = (
        deepseek_thinking_kwargs(model, effort=CONVERSATIONAL_REASONING_EFFORT)
        if thinking_enabled
        else thinking_off_kwargs(model)
    )
    response = await llm_request.acompletion(
        model=model,
        messages=messages,
        temperature=0.3,
        max_tokens=thinking_safe_max_tokens(model, _ANSWER_MAX_TOKENS),
        # Bounds establishing the stream; once chunks flow, stream_chunks
        # below owns the clock.
        timeout=_INTERVIEW_TOTAL_SECONDS,
        stream=True,
        **thinking_kwargs,
        api_key=api_key,
    )
    return await _collect_stream_content(response, sinks)


async def _emit(sink: ProseSink | None, text: str) -> None:
    """Relay ``text`` when there is both a sink and something to say."""
    if text and sink is not None:
        await sink(text)


async def _relay_chunk(
    chunk: Any, splitter: TurnSplitter, sinks: TurnSinks
) -> bool:
    """Relay one stream chunk's reasoning and prose to their sinks.

    ``reasoning_content`` is absent on non-thinking models and on providers
    that never reason. Content goes through the splitter rather than to the
    sink directly, so the trailing spec block is withheld from the scientist
    instead of appearing and then being retracted.

    Returns:
        Whether this chunk carried any reasoning text, so the caller can
        tell a turn that reasoned from one that never did.
    """
    if not chunk.choices:
        return False
    delta = chunk.choices[0].delta
    reasoning = getattr(delta, "reasoning_content", "") or ""
    await _emit(sinks.on_reasoning, reasoning)
    await _emit(sinks.on_prose, splitter.feed(delta.content or ""))
    return bool(reasoning)


async def _collect_stream_content(
    response: Any, sinks: TurnSinks
) -> tuple[str, dict[str, Any] | None, bool]:
    """Drain a streaming completion into relayed prose and parsed fields.

    Returns:
        The turn's whole prose, its parsed fields (None when the turn
        carried no usable spec block), and whether the model emitted any
        reasoning at all.
    """
    splitter = TurnSplitter()
    reasoned = False
    async for chunk in stream_chunks(
        response,
        stall_seconds=_INTERVIEW_STALL_SECONDS,
        total_seconds=_INTERVIEW_TOTAL_SECONDS,
    ):
        reasoned = await _relay_chunk(chunk, splitter, sinks) or reasoned
    trailing, whole, fields = splitter.finish()
    await _emit(sinks.on_prose, trailing)
    return whole, fields, reasoned


def _turn_response(
    interview: dict[str, Any], prose: str, fields: dict[str, Any] | None
) -> dict[str, Any]:
    """Assemble one turn's response from its prose and its parsed fields.

    A turn that carried no usable spec block keeps the interview's previous
    fields, which is why this is not an error: the fields are cumulative
    interview state, not a per-turn derivation, so "no block" and "this turn
    learned nothing new" are the same claim. Callers downstream cannot tell
    the difference, and must not -- the scientist still gets the prose.

    Args:
        interview: The durable interview row being advanced.
        prose: The turn's whole message to the scientist.
        fields: The parsed spec block, or None when there was none.

    Returns:
        The response object in the shape ``_resolved_turn`` reads.
    """
    if fields is None:
        logger.warning(
            "Interview turn carried no usable spec block; keeping fields"
        )
        return {
            "assistant_message": prose,
            **dict(interview["fields"]),
            "completed": False,
        }
    return {**fields, "assistant_message": prose}


@budgeted("interview")
async def _call_interview_model(
    interview: dict[str, Any],
    on_reasoning: ReasoningSink | None = None,
    on_prose: ProseSink | None = None,
) -> dict[str, Any]:
    """Call the configured interview model for one turn.

    Args:
        interview: The durable interview row being advanced.
        on_reasoning: Optional sink for live chain-of-thought fragments.
        on_prose: Optional sink for the answer's prose as it is written.

    Returns:
        The turn's response object.

    Raises:
        HTTPException: 503 on any provider or timeout failure, which
            ``_advance`` converts into the deterministic fallback turn. A
            missing or malformed spec block is *not* such a failure; see
            ``_turn_response``.
    """
    try:
        prose, fields = await _stream_interview_content(
            interview, TurnSinks(on_reasoning=on_reasoning, on_prose=on_prose)
        )
    except Exception as exc:
        logger.warning("Interview model failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="The interview Agent is temporarily unavailable.",
        ) from exc
    return _turn_response(interview, prose, fields)


def _fallback_interview_response(
    interview: dict[str, Any],
) -> dict[str, Any]:
    """Advance the five-field interview from explicit scientist answers.

    The recovery path never infers scientific content. It assigns each new
    answer to the field the Agent most recently requested, preserving a usable
    and resumable interview when the configured model is temporarily absent.
    The scripted sequence completes without eliciting lab constraints (K5):
    the field stays at its empty "none declared" state, which the engine
    treats as "no constraints". The turns it authors are marked as fallback
    when persisted (see ``interviews._resolved_turn``), so the UI can signal
    them as guided questions rather than silently passing them off as model
    output.
    """
    fields = dict(interview["fields"])
    user_turns = [
        str(turn["content"]).strip()
        for turn in interview["turns"]
        if turn["role"] == "user" and str(turn["content"]).strip()
    ]
    answers = user_turns[1:]
    if not fields.get("focus_area") and answers:
        fields["focus_area"] = [answers[0]]
    if not fields.get("preferences") and len(answers) > 1:
        fields["preferences"] = [answers[1]]
    completed = _ready(fields)
    if completed:
        message = "The research goal is ready for run configuration."
    elif not fields.get("focus_area"):
        message = (
            "Which scientific mechanisms or focus areas should this research "
            "prioritize?"
        )
    else:
        message = (
            "What constraints, available models or data, exclusions, and "
            "feasibility preferences should guide the work?"
        )
    return {
        "assistant_message": message,
        **fields,
        "completed": completed,
    }
