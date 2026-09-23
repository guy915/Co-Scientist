# M1-04b1b-r1 — Short scientific terms in claim retrieval

Classification: local design choice. No external repository code was copied.

The frozen Pro trials omitted two support examples before inference because
claim retrieval discarded short terms. The same defect reproduced on new
p53, DNA and Protein H examples through the public assessment interface.

The candidate keeps short alphanumeric terms containing a letter for retrieval,
filters a fixed common function-word set, and ranks by shared-term count. The
existing top-k limit and stable input-order tie break remain. All single/batch
assessment and freshness checks already share this retrieval function.
The lexical entailment tokenizer, scores and thresholds are unchanged.

Changing the shared verdict tokenizer was rejected: it would also alter the
support and contradiction safety heuristics. Adding entity-name exceptions was
rejected as too specific. A separate retrieval token set addresses evidence
admission without promoting an identifier match into entailment. The ordinary
long-term concept aliases remain available in retrieval.

Tests cover previously unseen identifiers, slash-separated identifiers,
short/long function-word false matches, bounded stable ranking, deterministic
abstention on identifier-only overlap and freshness invalidation. The batch
citation fixture now includes X on both passages to preserve its explicitly
intended equal-score tie; its expected cited passage is unchanged.

Limitations: terms that collide with the case-folded stopword set remain
excluded (A, I and NO are examples). Hyphen variants are not normalized into
one identifier. A short content term can admit an unrelated passage and occupy
a bounded candidate slot; the assessor must still decide what it supports.
This is a retrieval correction, not a semantic search model.

`retrieval-candidate-offline.json` binds the source hashes and dataset hash to
a retrieval-only observation: all 30 frozen challenge items now supply a
candidate passage. It contains no inference and establishes no scientific
accuracy. Both existing three-pair model comparisons remain failed evidence.
Scientific adoption requires a fresh matched baseline/candidate experiment,
unchanged .75 accuracy/.80 contradiction-recall gates, historical negative
controls, no material regression, verified free routing and actual served-model
records. Do not reuse prior live answers as new candidate results.
