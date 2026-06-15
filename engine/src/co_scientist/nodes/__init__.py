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
"""Workflow nodes for hypothesis generation.

Each node is a pure async function that takes state and returns updated state.
"""

from co_scientist.nodes.generate import generate_node
from co_scientist.nodes.literature_review import literature_review_node
from co_scientist.nodes.review import review_node
from co_scientist.nodes.ranking import ranking_node
from co_scientist.nodes.meta_review import meta_review_node
from co_scientist.nodes.evolve import evolve_node
from co_scientist.nodes.proximity import proximity_node
from co_scientist.nodes.supervisor import supervisor_node

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
