"""Deterministic offline backend: answers ``offline/``-prefixed models locally.

* ``llm``: the completion router that replaces the provider boundary.
* ``content``: what a generated leaf says, grounded in the prompt's goal.
* ``content_stopwords``: the word list ``content`` filters goal terms with.
* ``schema_fill``: the schema traversal that fills every property.

Nothing is imported here: callers name the module they use, and the router
installs itself only when asked (``llm.install_offline_router``).
"""
