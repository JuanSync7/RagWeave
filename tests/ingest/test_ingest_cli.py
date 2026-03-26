from src.ingest.cli import _build_parser


def test_verbose_stages_defaults_to_none():
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.verbose_stages is None


def test_verbose_stages_true_when_enabled():
    parser = _build_parser()
    args = parser.parse_args(["--verbose-stages"])
    assert args.verbose_stages is True


def test_verbose_stages_false_when_explicitly_disabled():
    parser = _build_parser()
    args = parser.parse_args(["--no-verbose-stages"])
    assert args.verbose_stages is False
