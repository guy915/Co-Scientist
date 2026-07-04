# Idea Generation — backend contract & config spec (extracted)

Extracted from the saved reference material in this folder:
- `system-prompt.md` — the agent's configuration-generation system prompt.
- `network/*.har` — 99 captured requests to the Discovery Engine widget API.

This is an **engine/data-model** reference (not UI). It documents how Google's
Gemini Enterprise "Idea Generation" turns a user goal into a run and what its
data model looks like, so our engine (`engine/src/co_scientist/`) can be checked
against it. Nothing here has been implemented — it's a map.

## 1. Config generation (`system-prompt.md`)

The first turn converts free-text user input into a `Config` textproto. Notable
because it's exactly what our **supervisor** node does when planning a run.

```proto
message Config {
  string title = 1;                         // short achievement title
  string goal = 2;                          // concrete, measurable, singular
  repeated string preferences = 3;          // hard scope constraints + soft "good idea" qualities
  repeated string self_play_instructions = 4;   // brainstorming/debate writer mode
  repeated string prompt_instructions = 5;       // meta-prompt writer mode
  repeated string text_instructions = 6;         // classic single-shot writer mode
  repeated string review_instructions = 7;       // for reviewers only; comparative, not a rephrase of preferences
  repeated Attribute attributes = 8;         // up to 3, shown in a table, used to STRATIFY ideas
  bool should_be_correct = 9;                // false only for e.g. fiction
  bool should_be_novel = 10;
  bool should_maximize_impact = 16;
  bool suggests_idea_contacts = 11;          // true for scientific goals
  bool follow_up_on_specific_research = 12;
  float offensive_score = 13;                // 1-5, HR-offensiveness gate
  bool is_personal_medical_recommendation = 14;
  bool is_personal_finance_recommendation = 15;
}
message Attribute { string name = 1; string extractor = 2; }  // extractor often a 1-5 rubric
```

Key ideas worth mirroring in our supervisor/config:
- **Three distinct writer modes** (self-play/debate, prompt-writer, classic
  text) each get their *own* instruction set — matches our generation modes
  (`engine/docs/GENERATION_MODES.md`); the reference keeps mode-specific
  guidance separate rather than sharing one prompt.
- **Preferences vs review-instructions vs attributes are strictly separated**:
  preferences = scope + quality constraints (used by writers *and* reviewers);
  review-instructions = comparative critique guidance (reviewers only, "focus
  on validating, not repeating preferences"); attributes = stratification axes
  shown in a table, each with a 1-5 extractor rubric.
- **Goal is always rephrased to singular + measurable + impact-oriented**, never
  a restatement of the user input; plural asks ("generate hypotheses") collapse
  to a singular idea definition.
- **Safety is structured, not prose**: `offensive_score` (1-5),
  `is_personal_medical_recommendation`, `is_personal_finance_recommendation` —
  compare to our `app/app/safety.py` screening. The reference gates at config
  time; we screen intake + final output.
- Self-critique loop is explicit: "generate proposals → critically evaluate →
  revise → only then emit textproto."

The `NO-CONFIG:` protocol handles chit-chat / empty input / positive-sentiment
turns without emitting a config (plain-text reply prefix). Example configs
(nuclear fusion, etc.) live in `system-prompt.md`.

## 2. Backend API surface (Discovery Engine widget API)

Host `discoveryengine.clients6.google.com`, base
`/v1alpha/locations/global/`. Every call wraps `{configId, additionalParams:
{token, origin}, <verb>Request: {...}}`.

| Endpoint | Purpose | Our equivalent |
|---|---|---|
| `widgetCreateSession` | start a run | `POST /api/runs` |
| `widgetStreamAssist` | streamed multi-agent generation | SSE `/api/runs/{id}/events` |
| `widgetGetSession` | run + turns (with answer details) | `GET /api/runs/{id}` |
| `widgetGetIdea` | one idea + reviews + Elo + matches | `GET /api/runs/{id}/hypotheses` |
| `widgetListSessions` | recents list | `GET /api/runs` |
| `widgetWriteUserEvent` | analytics | (n/a) |
| `widgetAdvancedCompleteQuery` | composer autocomplete | (n/a) |
| `widgetCreateUserAnnotation` / `widgetListUserAnnotations` | user notes on ideas | (n/a) |
| `widgetGetInstance` / `widgetStartInstance` | agent instance lifecycle | (n/a) |
| `widgetListSessionFileMetadata` | attached files | (n/a) |

`widgetStreamAssist` request carries the multi-agent shape:
`streamAssistRequest.{ session, query.parts[], agentsSpec.agentSpecs[],
toolsSpec.toolRegistry, answerGenerationMode, userMetadata.timeZone,
assistSkippingMode }`. Response is a **JSON array of streamed chunks**, each
`{uToken, streamAssistResponse.answer.{name, state, replies[{groundedContent}]}}`
— confirms the agents+tool-registry architecture we already have.

## 3. Idea / session data model (`widgetGetIdea`, `widgetGetSession`)

```
ideaForgeIdea {
  name, title, category,               // category → the doc breadcrumb text
  text { text },                       // full idea body
  summary { text },                    // short summary (idea-card snippet)
  reviews [ { text, score, type } ],   // per-review; type distinguishes review kinds
  reviewsSummary { text },             // "Review summary" section
  rank (int), eloRating (float),
  matchResult { numTotalMatches, numMatchesWon, winRate },   // "Match summary"
  matchDetails [ {                     // "Performance against other ideas"
    idea1, idea2, score,
    idea1RatingBefore/After, idea2RatingBefore/After,
    idea1RankBefore/After,   idea2RankBefore/After,
    reasonings, tier
  } ]
}
session {
  name, state, userPseudoId, displayName, labels[], ideaForgeInstance,
  startTime, endTime, expireTime,
  turns [ { query, assistAnswer, detailedAssistAnswer, turnId, createdAt,
            queryConfig, assistToken } ]
}
```

This maps almost 1:1 to our `Hypothesis` / `HypothesisReview` / `MatchRow` /
Elo model. Fields the reference surfaces that we could lean into:
- **`category`** — drives the doc breadcrumb (we synthesize one; theirs is a
  first-class field).
- **`matchResult.winRate` + `matchDetails[].{reasonings, tier}`** — the
  "Tournament performance → Performance against other ideas" section is a
  per-match narrative with before/after Elo & rank and a `tier`. Our tournament
  data has the ratings; the per-match `reasonings` + `tier` are what make their
  section readable.
- **`reviews[].type`** — distinct review kinds, not one blob.

## Not applicable to our UI

The `ideageneration_squircle_light.svg` agent icon
(`gstatic.com/vertexaisearch/icons/svg/…`) is Google's product icon for the
Idea Generation agent — their branding, not ours (we use the Co-Scientist
flask). Noted, not copied.
