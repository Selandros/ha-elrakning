import tempfile
from pathlib import Path

from scripts.check_custom_components_layout import invalid_custom_component_entries


def test_custom_components_root_accepts_only_importable_domain_directories():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "elrakning").mkdir()
        (root / "fresh_intellivent_sky").mkdir()

        assert invalid_custom_component_entries(root) == []


def test_custom_components_root_rejects_rollback_and_backup_entries():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "elrakning").mkdir()
        (root / ".elrakning-pre-1095").mkdir()
        (root / "rollback-elrakning").mkdir()
        (root / "stale.py").write_text("# not an integration root\n", encoding="utf-8")

        assert [path.name for path in invalid_custom_component_entries(root)] == [
            ".elrakning-pre-1095",
            "rollback-elrakning",
            "stale.py",
        ]
