<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Evolution agent — pseudocode

```
// Evolution agent
FUNCTION EvolveTopHypotheses()
BEGIN
 FETCH the top 5 hypotheses from the HypothesesList
 // Strategy 1: Combine ideas
 CALL LanguageModel with prompt: "Combine the best parts of [Hypothesis1] and
[Hypothesis2] into a new, stronger hypothesis."
 // Strategy 2: Simplify for clarity

 CALL LanguageModel with prompt: "Refine [Hypothesis3] to make it simpler and
more testable."
 // Strategy 3: Think differently
 CALL LanguageModel with prompt: "Inspired by these ideas, propose an
'out-of-the-box' alternative."
 // More strategies...
 FOR EACH EvolvedHypothesis generated DO
 // Treat it like a brand new idea
 SAVE EvolvedHypothesis to HypothesesList
 CREATE new Task (Agent: Reflection, Action: "ReviewHypothesis", TargetID:
EvolvedHypothesis.ID)
 ADD Task to GlobalTaskQueue
 END FOR
END
```
