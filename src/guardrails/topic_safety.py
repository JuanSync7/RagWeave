# @summary
# Topic safety rail using LLM-based on/off-topic classification.
# Adapted from NeMo's built-in topic_safety library action.
# Exports: TopicSafetyChecker, TopicSafetyResult
# Deps: src.guardrails.runtime, logging
# @end-summary
"""Topic safety rail for off-topic query detection.

This module uses an LLM-based classifier prompt to decide whether a request is
on-topic for the configured knowledge base. When the guardrails runtime is not
available, it fails open and lets upstream intent routing handle basics.

Requirements references (from internal docs): REQ-106.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.guardrails.common.schemas import RailVerdict
from src.guardrails.runtime import GuardrailsRuntime

logger = logging.getLogger("rag.guardrails.topic_safety")

# Configurable system prompt that defines what "on-topic" means
_DEFAULT_TOPIC_PROMPT = """\
You are a topic classifier for a knowledge base search system.

The system is designed to answer questions about documents in the knowledge base.
On-topic queries include:
- Questions about document content, concepts, or information retrieval
- Requests to search, find, explain, or summarize information
- Technical questions that could be answered from stored documents
- Follow-up questions about previous search results

Off-topic queries include:
- Personal questions (weather, jokes, games, time, music, stocks)
- Requests to perform actions outside of search (send emails, make calls)
- Creative writing tasks unrelated to the knowledge base
- General chitchat that is not a search query

{custom_instructions}

If any of the above conditions are violated, respond with "off-topic".
Otherwise, respond with "on-topic".
You must respond with "on-topic" or "off-topic"."""

REJECTION_MESSAGE = (
    "I'm designed to help you find information in the knowledge base. "
    "I can't help with that topic, but feel free to ask me a question "
    "about the documents I have access to."
)


@dataclass
class TopicSafetyResult:
    """Result of topic safety classification.

    Attributes:
        verdict: PASS/REJECT/MODIFY verdict.
        on_topic: Whether the query is classified as on-topic.
        message: Optional human-facing message for rejections.
    """

    verdict: RailVerdict
    on_topic: bool
    message: str = ""


class TopicSafetyChecker:
    """LLM-based topic safety classifier.

    Uses a configurable system prompt to determine if a user query is
    on-topic for the knowledge base. More robust than keyword matching
    for detecting off-topic queries.

    Adapted from NeMo Guardrails' built-in topic_safety action.
    """

    def __init__(
        self,
        custom_instructions: str = "",
    ) -> None:
        """Initialize a topic safety checker.

        Args:
            custom_instructions: Additional prompt instructions to refine the
                on-topic definition for a specific deployment/domain.
        """
        self._system_prompt = _DEFAULT_TOPIC_PROMPT.format(
            custom_instructions=custom_instructions,
        )

    def check(self, query: str) -> TopicSafetyResult:
        """Check if a query is on-topic for the knowledge base.

        Args:
            query: User input query text.

        Returns:
            `TopicSafetyResult` indicating whether the query is on-topic.
        """
        runtime = GuardrailsRuntime.get()
        if runtime.initialized and runtime.rails is not None:
            try:
                return self._check_with_llm(query)
            except Exception as e:
                logger.warning("Topic safety LLM check failed: %s — passing", e)

        # If no LLM available, pass through (intent classifier handles basics)
        return TopicSafetyResult(
            verdict=RailVerdict.PASS,
            on_topic=True,
        )

    def _check_with_llm(self, query: str) -> TopicSafetyResult:
        """Classify topic using an LLM prompt.

        Args:
            query: User input query text.

        Returns:
            `TopicSafetyResult` derived from the LLM's "on-topic"/"off-topic"
            response.
        """
        from src.retrieval.query_processor import _call_ollama

        result = _call_ollama(
            f"User message: {query}",
            system=self._system_prompt,
        )
        if result:
            answer = result.strip().lower()
            if "off-topic" in answer:
                logger.info("Topic safety: off-topic detected")
                return TopicSafetyResult(
                    verdict=RailVerdict.REJECT,
                    on_topic=False,
                    message=REJECTION_MESSAGE,
                )
            if "on-topic" in answer:
                return TopicSafetyResult(
                    verdict=RailVerdict.PASS,
                    on_topic=True,
                )

        # Ambiguous response — pass through
        return TopicSafetyResult(
            verdict=RailVerdict.PASS,
            on_topic=True,
        )
