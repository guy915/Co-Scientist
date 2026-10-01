"""Generate frontend wire types: python -m app.api_contracts.generate."""

from pathlib import Path

from app.api_contracts.registry import schemas
from app.api_contracts.typescript import declaration, references

API_DIR = Path(__file__).resolve().parents[2] / "frontend/src/api"
HEADER = "// Generated from app.api_contracts; edit the backend models.\n"


def generated_files() -> dict[str, str]:
    """Return deterministic source text, also used by the CI drift test."""
    definitions, owners = schemas()
    result = {}
    for group in sorted(set(owners.values())):
        names = sorted(name for name, owner in owners.items() if owner == group)
        needed = set().union(*(references(definitions[name]) for name in names))
        if "RunConfig" in names:
            needed.update({"JsonValue", "RunSetupConfig"})
        imports = []
        for owner in sorted(set(owners.values()) - {group}):
            refs = sorted(name for name in needed if owners[name] == owner)
            if refs:
                imports.append(
                    f"import type {{{', '.join(refs)}}} from './wire_{owner}';"
                )
        body = "\n\n".join(
            declaration(name, definitions[name]) for name in names
        )
        result[f"wire_{group}.ts"] = (
            HEADER + "\n".join(imports) + "\n\n" + body + "\n"
        )
    return result


def main() -> None:
    """Write all generated modules without depending on frontend tooling."""
    for name, content in generated_files().items():
        (API_DIR / name).write_text(content)


if __name__ == "__main__":
    main()
