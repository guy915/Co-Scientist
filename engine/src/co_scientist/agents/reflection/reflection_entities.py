"""Gene/protein entity extraction from hypothesis text.

Two-pass heuristic that pulls likely biomedical entity names (IL-6, KRAS,
TREM2) out of free-text hypotheses so the reflection node can query them
against the INDRA knowledge graph. Normalization and stop-word filtering keep
the results tight enough for single-agent INDRA queries.
"""

import re

# Matches hyphenated bio names first (IL-6, YKL-40, IL-1B), then standalone
# (KRAS, TREM2) hyphenated suffix is 1-2 digits + optional letter — avoids
# pathway notation like RAGE-JAK2
_HYPHENATED_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,5}-[0-9]{1,2}[A-Z]?)\b")
_STANDALONE_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,5})\b")

# Common false positives: english words, non-gene abbreviations, protein
# families
_STOP = frozenset(
    {
        # English
        "THE",
        "AND",
        "FOR",
        "WITH",
        "THIS",
        "THAT",
        "FROM",
        "INTO",
        "BUT",
        "NOT",
        "HAS",
        "CAN",
        "MAY",
        "WILL",
        "ARE",
        "WAS",
        "TWO",
        "ONE",
        "USE",
        "NEW",
        "ALL",
        "HOW",
        "ANY",
        "ITS",
        "VIA",
        "WHO",
        "WHY",
        "YET",
        "SET",
        "OUR",
        "OUT",
        "WAY",
        "TRY",
        "LET",
        "PUT",
        "GET",
        "END",
        "DID",
        "HIS",
        "HER",
        "BEEN",
        "ALSO",
        "SHOW",
        "THAN",
        "DOES",
        "SUCH",
        "HAVE",
        "MORE",
        "WELL",
        "MOST",
        "ONLY",
        "BOTH",
        "SOME",
        # tech/science abbreviations (not genes)
        "MCP",
        "LLM",
        "API",
        "PDF",
        "URL",
        "PCT",
        "KEY",
        "RED",
        "DNA",
        "RNA",
        "ATP",
        "ADP",
        "GDP",
        "GTP",
        "USA",
        "NIH",
        # Biomedical non-gene abbreviations
        "CSF",
        "CNS",
        "BBB",
        "PPI",
        "PET",
        "MRI",
        "CVE",
        "ROS",
        "iPSC",
        "CRISPR",
        "ELISA",
        "GWAS",
        "SNP",
        "DOID",
        "MESH",
        "HGNC",
        "CHEBI",
        # Protein families/classes (too broad for INDRA single-agent queries)
        "CYP450",
        "CSPG",
        "CSPGS",
    }
)

# Known informal → canonical mappings for common biomedical abbreviations
_ALIAS_MAP: dict[str, str] = {
    "RAGE": "AGER",
    "MK2": "MAPKAPK2",
    "P38": "MAPK14",
    "P53": "TP53",
    "BACE": "BACE1",
    "YKL40": "CHI3L1",
    "MCP1": "CCL2",
    "ABETA": "APP",
    "APOE4": "APOE",
}


def _normalize_entity(raw: str) -> str:
    """Normalize an extracted entity name for INDRA queries.

    Strips hyphens from bio names (IL-6 → IL6, YKL-40 → YKL40),
    applies known alias mappings (RAGE → AGER).
    """
    # Strip hyphen for names like IL-6, IL-15, YKL-40
    normalized = raw.replace("-", "")
    upper = normalized.upper()
    return _ALIAS_MAP.get(upper, normalized)


def _should_skip_entity(upper: str, seen: set[str]) -> bool:
    """True if a normalized entity name is a known stop-word or already seen."""
    return upper in _STOP or upper in seen


def _is_mutation_notation(raw: str) -> bool:
    """True if raw looks like a mutation notation rather than a gene name.

    Mutation notations (G12C, V600E, L858R) are a single letter followed by
    a digit; these are filtered out of the standalone-token pass.
    """
    return len(raw) >= 2 and raw[0].isupper() and raw[1].isdigit()


def _add_hyphenated_entities(
    hyphenated: list[str], seen: set[str], result: list[str]
) -> None:
    """Appends normalized hyphenated entity names to result (pass 1).

    Hyphenated names (IL-6, YKL-40) are higher-signal than standalone
    tokens, so they are processed first. Also marks each raw prefix as
    seen so e.g. "YKL" doesn't re-match after "YKL-40" in pass 2.

    Args:
        hyphenated: Raw hyphenated regex matches.
        seen: Upper-cased entity names already accepted; mutated in place.
        result: Normalized entity names accepted so far; mutated in place.
    """
    for raw in hyphenated:
        prefix = raw.split("-")[0].upper()
        seen.add(prefix)
        normalized = _normalize_entity(raw)
        upper = normalized.upper()
        if _should_skip_entity(upper, seen):
            continue
        seen.add(upper)
        result.append(normalized)


def _add_standalone_entities(
    standalone: list[str], seen: set[str], result: list[str], max_entities: int
) -> None:
    """Appends normalized standalone entity names to result (pass 2).

    Args:
        standalone: Raw standalone uppercase-token regex matches.
        seen: Upper-cased entity names already accepted; mutated in place.
        result: Normalized entity names accepted so far; mutated in place.
        max_entities: Stop once result reaches this length.
    """
    for raw in standalone:
        if len(result) >= max_entities:
            break
        if _is_mutation_notation(raw):
            continue
        normalized = _normalize_entity(raw)
        upper = normalized.upper()
        if _should_skip_entity(upper, seen):
            continue
        seen.add(upper)
        result.append(normalized)


def extract_entity_names(text: str, max_entities: int = 3) -> list[str]:
    """Extract likely gene/protein names from hypothesis text.

    Uses two-pass heuristic: first captures hyphenated bio names (IL-6, YKL-40),
    then standalone uppercase tokens (KRAS, TREM2). Normalizes and deduplicates.
    """
    hyphenated = _HYPHENATED_RE.findall(text)
    standalone = _STANDALONE_RE.findall(text)

    seen: set[str] = set()
    result: list[str] = []

    _add_hyphenated_entities(hyphenated, seen, result)
    _add_standalone_entities(standalone, seen, result, max_entities)

    return result[:max_entities]
