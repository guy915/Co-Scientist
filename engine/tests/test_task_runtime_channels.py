"""The durable path reduces exactly the channels LangGraph reduces.

``apply_task_update`` never invokes the graph, so it must find each
channel's reducer itself. It reads them off the state type's ``Annotated``
metadata, the same declaration LangGraph compiles, so a newly annotated
channel cannot fall through to last-write-wins on the durable path.
"""

import operator
from typing import Annotated

from langgraph.channels import BinaryOperatorAggregate
from langgraph.graph import StateGraph
from typing_extensions import TypedDict

from co_scientist.state import WorkflowState
from co_scientist.task_runtime import channel_reducers


class _ToyState(TypedDict):
    log: Annotated[list[int], operator.add]
    total: Annotated[int, operator.add]
    last: int


def test_only_annotated_channels_get_a_reducer() -> None:
    assert set(channel_reducers(_ToyState)) == {"log", "total"}


def test_a_list_channel_reduces_onto_an_empty_list_when_absent() -> None:
    reduce_log = channel_reducers(_ToyState)["log"]

    assert reduce_log(None, [1]) == [1]
    assert reduce_log([1], [2]) == [1, 2]


def test_a_non_list_channel_receives_the_existing_value_unchanged() -> None:
    assert channel_reducers(_ToyState)["total"](2, 3) == 5


def test_workflow_state_reducers_match_the_compiled_graph() -> None:
    compiled = StateGraph(WorkflowState).channels
    reduced_by_langgraph = {
        name
        for name, channel in compiled.items()
        if isinstance(channel, BinaryOperatorAggregate)
    }

    assert set(channel_reducers(WorkflowState)) == reduced_by_langgraph
