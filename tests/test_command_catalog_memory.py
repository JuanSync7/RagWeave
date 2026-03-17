from src.platform.command_catalog import MODE_CONSOLE_QUERY, MODE_SERVER_CLI, list_command_specs


def _names(mode: str) -> set[str]:
    return {spec.name for spec in list_command_specs(mode)}


def test_server_cli_includes_memory_commands():
    names = _names(MODE_SERVER_CLI)
    for expected in {"new-chat", "conversations", "switch", "history", "compact", "delete", "status"}:
        assert expected in names


def test_console_query_includes_memory_commands():
    names = _names(MODE_CONSOLE_QUERY)
    for expected in {"new-chat", "conversations", "switch", "history", "compact", "delete"}:
        assert expected in names
