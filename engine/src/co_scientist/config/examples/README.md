# Literature Review Tool Configuration Examples

This directory contains example YAML configurations for integrating external MCP servers and literature review tools with co-scientist-engine.

## Overview

Co-Scientist uses a **YAML-based configuration system** to decouple literature review tools from the core library. This allows you to:

- Bring your own MCP servers without modifying co-scientist-engine code
- Configure multiple literature sources (PubMed, arXiv, Google Scholar, etc.)
- Define custom response parsing, prompt instructions, and parameter mappings
- Mix and match tools from different MCP servers

The default configuration [../tools.yaml](../tools.yaml) provides a reference implementation using the bundled PubMed MCP server (See `mcp_server` at the top level of this repo).

## Content Parameters (`content_params`)

The `content_params` feature allows passing extra parameters to content tools. This is useful for tools that need context beyond just the URL:

### Supported Placeholders
- `{research_goal}` - The current research goal from workflow state
- `{focus_areas}` - List of focus areas (future: extracted from hypothesis categories)

### Example Usage
```yaml
workflows:
  literature_review:
    content_tool: "analyze_pdf_for_research"
    content_url_field: "pdf_url"
    content_params:
      research_goal: "{research_goal}"
      focus_areas:
        - "experimental methods"
        - "quantitative results"
```

This is particularly useful with the `analyze_pdf_for_research` tool, which generates questions dynamically based on the research context rather than extracting full text.

---

## INDRA CoGex Biomedical Domain Configuration

`indra_cancer.yaml` extends the default PubMed config with INDRA knowledge graph tools
(`merge_strategy: "extend"`), adapted for precision oncology hypothesis generation.

**Requirements:** PubMed MCP server on port 8888 with INDRA CoGex tools enabled.

| Config | Domain | Audience | Highlighted INDRA tools |
|---|---|---|---|
| `indra_cancer.yaml` | KRAS/NSCLC precision oncology | Oncology researchers | `query_mechanistic_statements`, `query_gene_codependents` (DepMap), `query_gene_disease_network` |

---

See the [literature review tools](../../../../docs/literature_review_tools_configuration.md) documentation for a guide and schemas on this topic.
