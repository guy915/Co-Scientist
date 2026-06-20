<!--
SOURCE (canonical, verbatim): references/google-co-scientist/research/papers/towards-an-ai-co-scientist.md
  Section A.6 "An example of tool use in the AI co-scientist with AlphaFold" / Figure A.40 (lines 1956-1964).
  Section-local references cited by the [3]-[7] markers below are reproduced from the A.6 reference list (lines 1970-1974).
PARALLEL SOURCE: references/google-co-scientist/research/supplements/accelerating-scientific-discovery-with-co-scientist-supplementary-information.md
  Supplementary Note 11 "An example of tool use in Co-Scientist with AlphaFold" (lines 1713-1719; Supplementary Fig. 9 caption at line 1769).
CASE STUDY: Tool use / protein design (general-purpose demonstration, not one of the three biomedical wet-lab validations).
ARTIFACT: a qualitative worked example of the AI co-scientist using AlphaFold as a validation tool to assess a proposed OCT4 protein modification. Figure A.40 itself is an image (predicted 3D structures + metrics); only its caption is extractable as text.
VERBATIM extract.
>>> VERSION DIVERGENCE (per the draft's de-dup rule, the arXiv body is kept verbatim and the divergence is noted, not silently reconciled):
    - arXiv (this file): "independently validated the modification using ESM-2 [6] and RoseTTAFold [7]. ESM-2 predicted an increased
      log-likelihood ratio and a similar predicted local distance difference test (pLDDT), and RoseTTAFold predicted similar
      confidence score (GDT) ...".
    - Nature SI Note 11: adds a THIRD validator, ESMFold — "validated the modification using ESM-2, ESMFold, and RoseTTAFold.
      ESM-2 predicted an increased log-likelihood ratio, ESMFold predicted a similar pLDDT, and RoseTTAFold predicted a similar GDT ...".
    The arXiv attributes the "similar pLDDT" to ESM-2; the SI attributes it to ESMFold. Numbers/tools not merged here.
-->

# AI co-scientist tool use with AlphaFold — OCT4 protein-design example (§A.6)

## A.6 An example of tool use in the AI co-scientist with AlphaFold

The AI co-scientist is a general purpose system broadly applicable across different areas of science and medicine. To better understand the capabilities and limitations of the system, we task it with the goal of suggesting protein sequences with specific properties. Determining the correct primary amino acid sequence with the desired properties is an essential part of protein engineering. While LLM-based systems can predict protein properties and suggest modifications [3], they can sometimes generate incorrect sequences (i.e., hallucinations). To address this, we integrate AlphaFold [4], a specialized AI system for predicting protein 3D structure, into our co-scientist. AlphaFold acts as a validation tool, evaluating the structural plausibility of sequences proposed by the co-scientist and provides feedback. This increases the reliability of the sequence design optimization process, which can be further validated with wet laboratory experiments. The approach to integrate tools highlights how specialized AI models can work in collaboration with more general AI systems like the AI co-scientist, facilitating the solution of complex challenges like protein design.

As an illustrative example, we used AlphaFold to assess a co-scientist's proposed modification to the OCT4 (octamer-binding transcription factor 4) protein (Appendix Figure A.40), one of the four Yamanaka factors [5], to increase binding affinity of its DNA binding domain. The co-scientist suggested adding a mechano-sensitive loop to the POU domain (a family of eukaryotic transcription factors) and a dynamic phosphorylation site outside of it. The co-scientist first verified the proposed sequence against the UniProt database via websearch. AlphaFold then predicted the 3D structure of the modified protein, suggesting that the modifications maintained structural stability. These predictions were used to refine the co-scientist's hypothesis, allowing it to improve its protein sequence design in subsequent iterations. We also independently validated the modification using ESM-2 [6] and RoseTTAFold [7]. ESM-2 predicted an increased log-likelihood ratio and a similar predicted local distance difference test (pLDDT), and RoseTTAFold predicted similar confidence score (GDT), compared to the original sequence. The insertion and modification did not seem to disrupt SOX2 and OCT4 interactions, indicated by the similar pLDDT scores between the original and modified OCT4 sequences. However, this example is for demonstration purposes only. Further in silico analysis (e.g., predicting binding affinity and off-target effects), and thorough laboratory validation are necessary to confirm that the proposed modifications actually improve the complex roles of OCT4 binding, while maintaining SOX2 interaction integrity, during pluripotency.

**Figure A.40** | AlphaFold predicted protein 3D structure and metrics for original OCT4 and AI co-scientist suggested modifications. (left panel) original OCT4 sequence with SOX2 and DNA binding (right panel) modified OCT4 sequence with SOX2 and DNA binding. The left 3D structure in each panel is the POU domain of the corresponding OCT4 sequence. The predicted template modeling (pTM) score, the interface predicted template modeling (ipTM), and predicted local distance difference test (pLDDT) are derived from the AlphaFold outputs.

Combining AlphaFold with the co-scientist framework offers a powerful approach for both improving existing proteins and designing entirely new ones. This integrated system allows researchers to iteratively optimize protein sequences for enhanced properties (e.g., stability, binding affinity, or catalytic activity) or putatively to create proteins with novel functions. It enables exploration of protein design while ensuring structural feasibility. Future work will focus on experimentally validating these capabilities and applying them to targeted protein design efforts as well as expansion to integration of other specialized AI tools with the co-scientist.

---

### Section-local references cited above (verbatim, from §A.6 reference list)

- [3] Wang, Y., He, J., Du, Y., Chen, X., Li, J. C., Liu, L.-P., Xu, X. & Hassoun, S. Large Language Model is Secretly a Protein Sequence Optimizer. arXiv preprint arXiv:2501.09274 (2025).
- [4] Jumper, J., Evans, R., Pritzel, A., Green, T., Figurnov, M., Ronneberger, O., Tunyasuvunakool, K., Bates, R., Žídek, A., Potapenko, A., et al. Highly accurate protein structure prediction with AlphaFold. Nature 596, 583–589 (2021).
- [5] Takahashi, K., Tanabe, K., Ohnuki, M., Narita, M., Ichisaka, T., Tomoda, K. & Yamanaka, S. Induction of pluripotent stem cells from adult human fibroblasts by defined factors. cell 131, 861–872 (2007).
- [6] Lin, Z., Akin, H., Rao, R., Hie, B., Zhu, Z., Lu, W., Smetanin, N., dos Santos Costa, A., Fazel-Zarandi, M., Sercu, T., Candido, S., et al. Language models of protein sequences at the scale of evolution enable accurate structure prediction. bioRxiv (2022).
- [7] Baek, M., DiMaio, F., Anishchenko, I., Dauparas, J., Ovchinnikov, S., Lee, G. R., Wang, J., Cong, Q., Kinch, L. N., Schaeffer, R. D., et al. Accurate prediction of protein structures and interactions using a three-track neural network. Science 373, 871–876 (2021).
