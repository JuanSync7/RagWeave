from src.platform.command_catalog import (
    MODE_CONSOLE_QUERY,
    MODE_INGEST_CLI,
    MODE_QUERY_CLI,
    MODE_SERVER_CLI,
    get_command_spec,
    list_command_specs,
    to_payload,
)


def _names(mode: str, **kwargs) -> set[str]:
    return {spec.name for spec in list_command_specs(mode, **kwargs)}


def test_server_cli_includes_memory_commands():
    names = _names(MODE_SERVER_CLI)
    for expected in {"new-chat", "conversations", "switch", "history", "compact", "delete", "status"}:
        assert expected in names


def test_console_query_includes_memory_commands():
    names = _names(MODE_CONSOLE_QUERY)
    for expected in {"new-chat", "conversations", "switch", "history", "compact", "delete"}:
        assert expected in names


def test_list_command_specs_filters_by_mode():
    """Commands not registered for a mode must not appear in that mode's list."""
    server_names = _names(MODE_SERVER_CLI)
    ingest_names = _names(MODE_INGEST_CLI)
    # "set-dir" is ingest-only; must not appear in server_cli
    assert "set-dir" not in server_names
    assert "set-dir" in ingest_names


def test_hidden_commands_excluded_by_default():
    """Hidden commands are suppressed unless include_hidden=True."""
    names_default = _names(MODE_SERVER_CLI)
    names_with_hidden = _names(MODE_SERVER_CLI, include_hidden=True, allow_admin=True)
    # "_raw-health" is hidden and admin_only in MODE_SERVER_CLI
    assert "_raw-health" not in names_default
    assert "_raw-health" in names_with_hidden


def test_get_command_spec_returns_matching_spec():
    spec = get_command_spec(MODE_SERVER_CLI, "new-chat")
    assert spec is not None
    assert spec.name == "new-chat"
    assert spec.intent == "new_conversation"


def test_get_command_spec_returns_none_for_wrong_mode():
    """A command from one mode is not visible in an unrelated mode."""
    spec = get_command_spec(MODE_QUERY_CLI, "set-dir")
    assert spec is None


def test_to_payload_serializes_specs():
    specs = list_command_specs(MODE_SERVER_CLI)
    payload = to_payload(specs)
    assert isinstance(payload, list)
    assert all(isinstance(item, dict) for item in payload)
    # Each item must have the canonical keys
    for item in payload:
        assert "name" in item
        assert "description" in item
        assert "modes" in item


def test_memory_command_intent_strings_are_correct():
    """Memory-related commands must declare the expected intent strings."""
    specs = list_command_specs(MODE_SERVER_CLI)
    intent_map = {spec.name: spec.intent for spec in specs}
    assert intent_map["switch"] == "switch_conversation"
    assert intent_map["compact"] == "compact_conversation"
    assert intent_map["new-chat"] == "new_conversation"
