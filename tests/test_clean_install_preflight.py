import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs


install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning import site_identity  # noqa: E402


class _MemoryStore:
    data = {
        "site": {"site_id": "legacy", "name": "Legacy", "current": True},
        "sites": [{"site_id": "legacy", "name": "Legacy", "current": True}],
        "active_site_id": "legacy",
        "site_configs": {"legacy": {"power": {}, "meter": {}, "bindings": {}}},
        "global_bindings": {"legacy": True},
        "ledger": [{"site_id": "legacy", "generation_id": "old"}],
    }

    def __init__(self, *_args, **_kwargs):
        pass

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data
        type(self).data = data


class CleanInstallPreflightTests(unittest.TestCase):
    def test_archive_metadata_is_bounded_and_provenance_fingerprinted(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "elrakning" / "legacy-bundles" / "test"
            bundle.mkdir(parents=True)
            (bundle / "README.md").write_text("archive\n", encoding="utf-8")
            (bundle / "SHA256SUMS").write_text("file hash\n", encoding="utf-8")
            hass = SimpleNamespace(config=SimpleNamespace(path=lambda: root))

            metadata = site_identity.clean_install_archive_metadata(hass, str(bundle))

            assert metadata["archive_reference"] == str(bundle.resolve())
            assert metadata["archive_manifest_sha256"] == hashlib.sha256(
                b"file hash\n"
            ).hexdigest()

    def test_pending_reset_is_idempotent_and_rejects_invalid_archive(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "elrakning" / "legacy-bundles" / "test"
            bundle.mkdir(parents=True)
            (bundle / "README.md").write_text("archive\n", encoding="utf-8")
            (bundle / "SHA256SUMS").write_text("file hash\n", encoding="utf-8")
            hass = SimpleNamespace(config=SimpleNamespace(path=lambda: root))
            original_store = site_identity.Store
            site_identity.Store = _MemoryStore
            try:
                result = asyncio.run(site_identity.async_prepare_pending_clean_install(
                    hass,
                    {"archive_reference": str(bundle), "confirm": True},
                ))
                assert result["clean_install"]["state"] == "empty"
                assert result["clean_install"]["archive_manifest_sha256"]
                second = asyncio.run(site_identity.async_prepare_pending_clean_install(
                    hass,
                    {"archive_reference": str(bundle), "confirm": True},
                ))
                assert second["changed"] is False
                with self.assertRaises(ValueError):
                    asyncio.run(site_identity.async_prepare_pending_clean_install(
                        hass,
                        {"archive_reference": str(Path(root) / "other"), "confirm": True},
                    ))
            finally:
                site_identity.Store = original_store

    def test_archive_metadata_accepts_readme_txt_and_stays_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "elrakning" / "legacy-bundles" / "text-readme"
            bundle.mkdir(parents=True)
            (bundle / "README.txt").write_text("archive\n", encoding="utf-8")
            (bundle / "SHA256SUMS").write_text("file hash\n", encoding="utf-8")
            hass = SimpleNamespace(config=SimpleNamespace(path=lambda: root))

            metadata = site_identity.clean_install_archive_metadata(hass, str(bundle))

            assert metadata["archive_reference"] == str(bundle.resolve())
            (bundle / "README.txt").unlink()
            with self.assertRaises(ValueError) as error:
                site_identity.clean_install_archive_metadata(hass, str(bundle))
            assert str(error.exception) == "archive_bundle_incomplete"
