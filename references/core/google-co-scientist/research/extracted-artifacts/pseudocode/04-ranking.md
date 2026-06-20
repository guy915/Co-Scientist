<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Ranking agent — pseudocode

```
// Ranking agent
FUNCTION AddToTournament(HypothesisID)
BEGIN
 // Retrieve the specified hypothesis from our central data store
 LET HypothesisToAdd = FETCH Hypothesis FROM SharedMemory WHERE ID is
HypothesisID
 // Check if this hypothesis is already in the tournament. If so, do nothing
 IF HypothesisToAdd.EloRating IS NOT empty THEN
 PRINT "Warning: Hypothesis [HypothesisID] is already in the tournament."
 EXIT function
 END IF
 // Assign the standard starting Elo score
 SET HypothesisToAdd.EloRating TO 1200
 // Save the updated hypothesis back to the central data store
 UPDATE Hypothesis in SharedMemory
END
FUNCTION RunTournamentBatch()
BEGIN
 SELECT two hypotheses to compare (HypothesisA, HypothesisB)
 // Prioritize new hypotheses or those with similar Elo ratings
 CALL LanguageModel with prompt: "Simulate a debate between two scientists, one
defending HypothesisA and one defending HypothesisB. Conclude by declaring which
one is superior."
 DETERMINE the winner (e.g., HypothesisA) and loser (HypothesisB) from the debate
 CALCULATE new Elo ratings for both hypotheses based on the outcome
 UPDATE HypothesisA.EloRating and HypothesisB.EloRating in SharedMemory
END
```
