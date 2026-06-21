<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Reflection agent — pseudocode

```
// Reflection agent
FUNCTION ReviewHypothesis(HypothesisID)
BEGIN
 FETCH Hypothesis from SharedMemory using HypothesisID
 // Perform full review
 PERFORM web search for evidence related to the Hypothesis
 CALL LanguageModel with prompt: "Critically review this hypothesis for novelty
and correctness using the provided literature."
 CREATE FullReview and SAVE to ReviewsList
 // Perform deep verification
 CALL LanguageModel with prompt: "Break down this hypothesis into its core
assumptions."
 FOR EACH Assumption DO
 CHECK if the assumption is scientifically plausible
 END FOR
 CREATE VerificationReview and SAVE to ReviewsList
 // Create next step
 CREATE new Task (Agent: Ranking, Action: "AddToTournament", TargetID:
HypothesisID)
 ADD Task to GlobalTaskQueue
END
```
