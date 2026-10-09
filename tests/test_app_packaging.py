from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_repository_metadata_and_app_layout_are_discoverable():
    repository = yaml.safe_load((ROOT / "repository.yaml").read_text())
    assert repository["name"]
    assert repository["url"] == "https://github.com/Selandros/ha-elrakning"
    assert repository["maintainer"]

    app_config = yaml.safe_load((ROOT / "app/config.yaml").read_text())
    assert app_config["slug"] == "elrakning_app"
    assert (ROOT / "app/Dockerfile").is_file()
    assert (ROOT / "app/run.sh").is_file()
    assert (ROOT / "app/elrakning_app/app_contract.py").is_file()
    assert (
        (ROOT / "app/elrakning_app/app_contract.py").read_text()
        == (ROOT / "custom_components/elrakning/app_contract.py").read_text()
    )


def test_app_dockerfile_uses_standalone_app_build_context():
    dockerfile = (ROOT / "app/Dockerfile").read_text()
    assert "COPY elrakning_app /app/elrakning_app" in dockerfile
    assert "COPY run.sh /run.sh" in dockerfile
    assert "COPY app/" not in dockerfile
    assert "COPY custom_components/" not in dockerfile
