# @summary
# Conversation memory facade package: provider singleton and schema exports.
# Exports: ConversationMemoryProvider, ConversationMeta, ConversationSummary, ConversationTurn,
#          MemoryContext, get_conversation_memory, conversation_meta_to_dict, conversation_turns_to_dict
# Deps: src.platform.memory.provider, src.platform.memory.schemas
# @end-summary
"""Conversation memory platform facade.

This package exposes a stable import surface for conversation memory services.
"""

from src.platform.memory.provider import (
    ConversationMemoryProvider,
    conversation_meta_to_dict,
    conversation_turns_to_dict,
    get_conversation_memory,
)
from src.platform.memory.schemas import ConversationMeta, ConversationSummary, ConversationTurn, MemoryContext

__all__ = [
    "ConversationMemoryProvider",
    "ConversationMeta",
    "ConversationSummary",
    "ConversationTurn",
    "MemoryContext",
    "conversation_meta_to_dict",
    "conversation_turns_to_dict",
    "get_conversation_memory",
]
