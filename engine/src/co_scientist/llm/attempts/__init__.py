"""One attempt and what follows it: the loop, the ladder, the waits.

The single-attempt completion primitive (``single``) and the one loop that
retries it for ``call_llm``, ``call_llm_json`` and the tool turn
(``retry.run_attempts``, in the vocabulary of ``contract``). The ladder of
rungs it climbs is ``escalation``, the platform-cap classification is
``park``, the wait schedules are ``backoff``, and ``json_attempt`` is
``call_llm_json``'s judge of a response.
"""
