import ast
from pathlib import Path


WATCHER = Path(__file__).parents[1] / "tools" / "elrakning_runtime_watcher.py"


def test_external_watcher_is_read_only_and_bounded():
    source = WATCHER.read_text(encoding="utf-8")
    ast.parse(source)
    assert "ha core info" in source
    assert "ha core stats" in source
    assert "ha jobs info" in source
    assert "ha supervisor logs" in source
    assert "ha core logs" in source
    assert "curl" in source
    assert "ha core restart" not in source
    assert "ha core stop" not in source
    assert "ha core start" not in source
    assert "--max-time 2" in source
    assert "BatchMode=yes" in source
