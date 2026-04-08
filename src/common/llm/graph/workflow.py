# @summary
# Thin builder API over LangGraph StateGraph.
# Exports: workflow, WorkflowBuilder, CompiledWorkflow
# Deps: langgraph.graph, src.common.llm.schemas
# @end-summary
"""Generic workflow builder wrapping LangGraph's StateGraph.

Callers use ``workflow(state_schema)`` to get a ``WorkflowBuilder``,
add steps/edges/routes, then ``compile()`` into a ``CompiledWorkflow``
that can be run synchronously, asynchronously, or streamed.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

from langgraph.graph import END, StateGraph  # noqa: F401

__all__ = ["workflow", "WorkflowBuilder", "CompiledWorkflow"]


class CompiledWorkflow:
    """Executable wrapper around a compiled LangGraph graph."""

    def __init__(self, graph) -> None:
        self._graph = graph

    def run(self, initial_state: dict, *, config: dict | None = None) -> dict:
        """Execute the workflow synchronously and return the final state."""
        return self._graph.invoke(initial_state, config=config)

    async def arun(self, initial_state: dict, *, config: dict | None = None) -> dict:
        """Execute the workflow asynchronously and return the final state."""
        return await self._graph.ainvoke(initial_state, config=config)

    def stream(
        self, initial_state: dict, *, config: dict | None = None
    ) -> Iterator[tuple[str, dict]]:
        """Yield ``(step_name, state)`` tuples as the workflow progresses."""
        for event in self._graph.stream(initial_state, config=config):
            for step_name, state in event.items():
                yield step_name, state


class WorkflowBuilder:
    """Fluent builder that assembles a LangGraph StateGraph."""

    def __init__(self, state_schema: type) -> None:
        self._graph = StateGraph(state_schema)
        self._entry: str | None = None

    def add_step(self, name: str, fn: Callable[[dict], dict]) -> "WorkflowBuilder":
        """Add a processing node. *fn* receives state and returns a partial update."""
        self._graph.add_node(name, fn)
        return self

    def add_edge(self, from_step: str, to_step: str) -> "WorkflowBuilder":
        """Add a direct edge between two steps (use ``END`` for terminal)."""
        self._graph.add_edge(from_step, to_step)
        return self

    def add_route(
        self, from_step: str, router_fn: Callable[[dict], str]
    ) -> "WorkflowBuilder":
        """Add conditional branching from *from_step* using *router_fn*."""
        self._graph.add_conditional_edges(from_step, router_fn)
        return self

    def set_entry(self, step_name: str) -> "WorkflowBuilder":
        """Designate *step_name* as the workflow entry point."""
        self._entry = step_name
        return self

    def compile(self, *, checkpointer: Any = None) -> CompiledWorkflow:
        """Compile the graph into an executable ``CompiledWorkflow``.

        Parameters
        ----------
        checkpointer:
            Optional checkpoint backend (e.g. from ``checkpoint.py``).
        """
        if self._entry is None:
            raise ValueError("Entry point not set — call set_entry() before compile()")
        self._graph.set_entry_point(self._entry)
        compiled = self._graph.compile(checkpointer=checkpointer)
        return CompiledWorkflow(compiled)


def workflow(state_schema: type) -> WorkflowBuilder:
    """Create a new workflow builder for the given state schema."""
    return WorkflowBuilder(state_schema)
