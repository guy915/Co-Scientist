# M1 PubMed campaign isolation and TLS correction

Two validated diff-scan candidates in scan `37397870-2c59-4fa1-b638-30445fd598f6` identified a shared MCP Entrez credential path and a default TLS-verification inversion in the frozen campaign revision `c3cdef26`.

- **Local design choice:** Campaign PubMed calls now pass `api_key=None` per Biopython request, which its parameter constructor omits from the wire even if the process-global `Entrez.api_key` was loaded for ordinary users. The campaign rate limiter uses the anonymous 3/s pacing. Ordinary non-campaign requests retain their existing key and 10/s pacing.
- **Security correction:** Entrez initialization no longer changes Python's global HTTPS context. An inherited `DISABLE_SSL_VERIFY=true` now fails closed before initialization; the insecure option was removed from the MCP example configuration.

This preserves public PubMed search for campaign research without borrowing a service credential. It does not claim any official Google implementation detail.

Behavioral regressions were red first in `engine/mcp_server/tests/test_entrez_campaign_isolation.py`: default TLS context was replaced, campaign pacing used the shared-key interval, and the explicit insecure setting did not fail. After the fix, 15 targeted MCP tests passed, as did the full MCP suite (283 tests and mypy over 73 source files). Ruff and `git diff --check` passed. The test constructs a real Biopython PubMed request while intercepting the network opening; it checks the serialized request contains neither the service key nor an explicit caller key. Deployment and a live public-interface recheck remain under M1's release item.
