# Pro qualification failure analysis

Status: two completed pairs; third pair running. No model selected and no
candidate adopted. Evidence is the committed `opposition-pro-*` artifacts,
the frozen `citation_entailment_challenge_v1.json`, and candidate source
`06a17a70`. Indices below are zero-based dataset positions.

Pair 2 candidate accuracy is 21/30 (.70), below .75; contradiction recall is
8/10 (.80). Baseline accuracy is 13/30 (.433), recall 0/10. Pair 1 candidate
accuracy is 23/30 (.767), recall 8/10. Passing pair 1 does not cancel pair 2.

| Pair 2 failures | Observed path | Next investigation |
| --- | --- | --- |
| 5, 6: species; 8, 29: time; 11: topic | Primary model returns partial; no opposition verification applies | Clarify the general entailment contract for mandatory population/endpoint/time conditions; preserve legitimate partial support |
| 19, 27: paraphrased support | No physical model request; lexical retrieval returns zero passages | Investigate bounded semantic retrieval or candidate retention without promoting unrelated evidence |
| 21: paraphrased contradiction | Primary says contradicts; quote coverage .20 fails existing .25 eligibility floor | Assess a semantic identity check without abandoning the historical false-contradiction controls |
| 24: direction reversal | Primary says contradicts; secondary verifier returns false for same_conditions and mutually_exclusive | Investigate how the verifier treats intervention direction versus the causal claim; retain caution about causal inference |

The primary prompt permits adjacent findings and narrower conditions as partial
support. The frozen dataset expects insufficient where a claim's required human
population or time endpoint is untested. This contract ambiguity is distinct
from transport compatibility. The primary model also calls topic-only item 11
partial, despite the prompt explicitly excluding topic-only evidence.

Offline reproduction through `retrieve_passages`, `_tokens`, and `_lexical_score`
confirmed zero coverage/retrieval for 19 and 27. One-letter identifiers Q, G, D
are absent from the claim token sets. Item 21 has coverage .20 and is retrieved;
item 24 has .50 and reaches semantic verification. These source files have no
diff from the pinned candidate revision. This was a pure local calculation,
not a new live trial or an independent expert validation of dataset labels.

The same two support omissions occur in both baseline and candidate trials.
Baseline partial errors number four and five; candidate partial errors three
and five. Thus the extra opposition check explains recovered contradictions,
not the pre-existing retrieval limitation or all primary classification errors.

Keep the running third pair unchanged. Do not lower gates, alter expected labels,
add example-specific keywords, or count partial as correct to qualify this run.
Any subsequent changed candidate requires new matched evidence under the campaign
contract. This analysis identifies investigation seams, not accepted fixes.
