import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SERVICE_NAME = "greenely_proof_provision"
EXPECTED_FIELDS = {
    "site_id",
    "expected_binding_fingerprint",
    "contract_id",
    "facility_meter_id_fingerprint",
    "facility_meter_identity_state",
    "contract_meter_id_fingerprint_or_state",
    "invoice_installation_identity_fingerprint",
    "verification_method",
    "parser_identity",
    "normalization_identity",
    "evidence_reference",
    "evidence_digest",
    "evidence_package",
}


def test_services_yaml_describes_the_registered_greenely_proof_service():
    service_path = ROOT / "custom_components" / "elrakning" / "services.yaml"
    document = yaml.safe_load(service_path.read_text(encoding="utf-8"))

    assert set(document) == {SERVICE_NAME}
    service = document[SERVICE_NAME]
    assert set(service["fields"]) == EXPECTED_FIELDS
    assert all(field["required"] is True for name, field in service["fields"].items() if name != "facility_meter_identity_state" and name != "facility_meter_id_fingerprint")
    assert service["fields"]["facility_meter_id_fingerprint"]["required"] is False
    assert service["fields"]["facility_meter_identity_state"]["required"] is False
    assert service["fields"]["evidence_package"]["selector"] == {"object": {}}


def test_services_yaml_fields_match_registered_provision_schema():
    source = (
        ROOT
        / "custom_components"
        / "elrakning"
        / "elhandel"
        / "providers"
        / "greenely_invoice_economics.py"
    ).read_text(encoding="utf-8")
    manifest = json.loads(
        (ROOT / "custom_components" / "elrakning" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert 'SERVICE_PROVISION = "greenely_proof_provision"' in source
    assert "vol.Required(\"evidence_package\"): dict" in source
    assert manifest["domain"] == "elrakning"
