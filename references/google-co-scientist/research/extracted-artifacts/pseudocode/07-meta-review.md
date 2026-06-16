<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Meta-review agent — pseudocode

```
// Meta-review agent
FUNCTION GenerateSystemFeedback()
BEGIN
 GATHER all reviews and tournament debate transcripts from SharedMemory
 CALL LanguageModel with prompt: "Analyze all these critiques. What are the most
common weaknesses (e.g., 'lacks a clear experimental plan') and strengths?
Summarize this as feedback for the whole system."
 UPDATE SystemWideFeedback in SharedMemory with this summary
END
FUNCTION GenerateFinalResearchOverview()
BEGIN
 FETCH the top 10 hypotheses from SharedMemory

 CALL LanguageModel with prompt: "Synthesize these top-ranked hypotheses into a single, coherent research overview for the scientist. Outline the main research directions and their justifications."

 RETURN the generated overview END
```
