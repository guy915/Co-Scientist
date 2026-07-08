"""Workflow nodes for hypothesis generation.

Each node is a pure async function that takes state and returns updated state.
"""

# Re-exports the node entry points that HypothesisGenerator wires together
# into the LangGraph StateGraph (see generator.py), so graph-building code
# imports every node from this one package rather than reaching into each
# node's own module.
from co_scientist.nodes.generate import generate_node
from co_scientist.nodes.literature_review import literature_review_node
from co_scientist.nodes.review import review_node
from co_scientist.nodes.ranking import ranking_node
from co_scientist.nodes.meta_review import meta_review_node
from co_scientist.nodes.evolve import evolve_node
from co_scientist.nodes.proximity import proximity_node
from co_scientist.nodes.supervisor import supervisor_node

# Explicit export list keeps `from co_scientist.nodes import *` (and linters)
# scoped to the public node callables, not internal helper modules.
__all__ = [
    "generate_node",
    "literature_review_node",
    "review_node",
    "ranking_node",
    "meta_review_node",
    "evolve_node",
    "proximity_node",
    "supervisor_node",
]
