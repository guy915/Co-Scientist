# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""INDRA CoGex knowledge graph tool implementations."""

from mcp_server.tools.indra_cogex.associations import (
    query_gene_disease_network,
    query_gene_codependents,
)
from mcp_server.tools.indra_cogex.drug_clinical import (
    query_drug_info,
    query_clinical_trials,
)
from mcp_server.tools.indra_cogex.pathways import (
    query_pathways,
    query_causal_subnetwork,
)
from mcp_server.tools.indra_cogex.statements import query_mechanistic_statements
from mcp_server.tools.indra_cogex.enrichment import run_enrichment_analysis

__all__ = [
    "query_gene_disease_network",
    "query_gene_codependents",
    "query_drug_info",
    "query_clinical_trials",
    "query_pathways",
    "query_causal_subnetwork",
    "query_mechanistic_statements",
    "run_enrichment_analysis",
]
