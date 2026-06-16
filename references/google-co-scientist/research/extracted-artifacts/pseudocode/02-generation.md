<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Generation agent — pseudocode

```
// Generation agent
FUNCTION CreateInitialHypotheses()
BEGIN
 // Strategy 1: Use existing knowledge
 PERFORM a web search for literature related to the ResearchGoal

 CALL LanguageModel with prompt: "Based on this research, propose a novel
hypothesis for [ResearchGoal]." 
 // Strategy 2: Simulate debate
 CALL LanguageModel with prompt: "Simulate a scientific debate between experts to
create a new hypothesis for [ResearchGoal]."
 // More strategies...
 // Process new ideas
 FOR EACH NewHypothesis generated DO
 SAVE NewHypothesis to HypothesesList in SharedMemory
 CREATE new Task (Agent: Reflection, Action: "ReviewHypothesis", TargetID:
NewHypothesis.ID)
 ADD Task TO GlobalTaskQueue
 END FOR
END
```
