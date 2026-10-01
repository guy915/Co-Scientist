"""Progressive broadening for keyword literature queries.

Literature back ends AND every term of a keyword query, so a query's hit
count collapses as terms are added. Measured against PubMed for one run's
own generated queries:

    mifepristone glioblastoma                              16 hits
    mifepristone glucocorticoid receptor glioblastoma        1 hit
    mifepristone glucocorticoid receptor antagonist
        glioblastoma blood brain barrier PD-L1               0 hits

A model asked for "keywords" naturally writes the long form -- it reads as
the most precise description of what is wanted -- and gets nothing back.
Nothing downstream distinguishes that from "no such literature exists", so
the run proceeds with an evidence pool that never covers the ideas it went
on to generate, and the claim gate then quarantines them for lacking
support that was never fetched.

Broadening a query that returned nothing costs one more call and cannot
lose anything: there were no results to lose.
"""

from __future__ import annotations

# Two terms still name a topic ("mifepristone glioblastoma"); one term is a
# subject heading that would swamp the budget with unrelated papers.
_MIN_QUERY_TERMS = 2


def broadened_queries(query: str) -> list[str]:
    """Return progressively broader forms of ``query``, narrowest first.

    Halving rather than dropping one term at a time keeps the ladder to at
    most two extra calls on the run's serial spine while still reaching the
    productive range: the nine-term query above returns nothing until its
    fifth term is dropped, and one-at-a-time would have spent five calls
    discovering that.

    Terms are dropped from the end because query formulation appends
    qualifiers -- mechanism and setting come first, hedges and endpoints
    last -- so a prefix stays on topic while a suffix is what over-constrains
    it.

    Args:
        query: The keyword query as formulated, terms separated by spaces.

    Returns:
        The query followed by any broader forms, each strictly shorter than
        the last. A query already at or below the floor yields just itself.
    """
    terms = query.split()
    if len(terms) <= _MIN_QUERY_TERMS:
        return [query]

    ladder = [query]
    for count in ((len(terms) + 1) // 2, _MIN_QUERY_TERMS):
        broader = " ".join(terms[:count])
        if count < len(terms) and broader not in ladder:
            ladder.append(broader)
    return ladder
