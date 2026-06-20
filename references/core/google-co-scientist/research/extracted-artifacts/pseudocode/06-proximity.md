<!-- SOURCE (verbatim): ../../supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md · Supplementary Note 8 (lines 905-1099).
One part of the single integrated Note 8 listing: the Supervisor's main loop
orchestrates every agent via a shared task queue. Pseudocode is verbatim; the
source's stray "None" tokens and split code fences (export artifacts) are omitted. -->

# Proximity agent — pseudocode

```
// Proximity agent
FUNCTION UpdateProximityGraph()
BEGIN
 FOR EACH pair of hypotheses in the HypothesesList DO
 CALCULATE a similarity score between them (e.g., using text embeddings)
 UPDATE the connection between them in the ProximityGraph
 END FOR
END
```
