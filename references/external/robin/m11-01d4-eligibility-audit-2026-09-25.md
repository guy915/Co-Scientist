# M11-ROBIN-01d4 eligibility audit (read-only)

Date: 2026-09-25

**Disposition:** overall eligible-run existence is **unknown**. The retained campaign-owned production run is **ineligible**. 01d4 cannot proceed on that run, and it cannot make a live refinement request without a newly qualified exact-zero route.

The acceptance item in `PLAN.md` requires a completed campaign-owned public run with an eligible hypothesis. Its fallback is a bounded public run if no such run exists. The retained receipt `m11-public-run-state.json` identifies campaign run `987574df-557e-48fa-a77b-1f5692e3876b`: it paused at final safety review with zero hypotheses after eight generation-strategy failures (`zero-cost model is not an explicit catalog route`). The receipt records no attached documents, notifications disabled, web search disabled, and $0.00 reported model cost. No refinement was attempted. This run cannot satisfy 01d4.

The release receipts `m11-release-verification.json` and `m11-ui-release-verification.json` both leave live refinement open and report no eligible completed campaign-owned run at their verification points. The later `PLAN.md` M11-OPS-02b entry records that the Nex route disappeared. Its Qwen replacement probe returned a shared-pool 429, with no served-model or usage receipt and no qualification. There is therefore no recorded current exact-zero route admitted for a live refinement call.

I could not prove access to the campaign owner's production inventory. The public workbench opened in this session showed no recent sessions, which does not establish the campaign owner's identity or inventory. `COSCIENTIST_API_URL`, `COSCIENTIST_CLIENT_ID`, and researcher-token environment variables were unset. The CLI's fallback creates a new local client ID, so I did not use it. I did not inspect the production database backup or other users' runs or documents, and made no run-lifecycle, model-inference, or mutation requests.

**Decision:** do not mark 01d4 eligible or complete. Whether another already completed eligible campaign run exists remains unknown. First obtain a verified campaign-owner session and inspect only that owner's run inventory. If no eligible run exists, the live acceptance still needs the smallest bounded public run, after an exact-zero replacement route is qualified and released under M11-OPS-02b/02c. Keep 01d4 open.
