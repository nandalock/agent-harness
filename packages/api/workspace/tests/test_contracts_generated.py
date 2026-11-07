"""The committed TypeScript contracts must match the Python controllers."""
from scripts.generate_rpc_contracts import OUTPUT, render_contracts


def test_generated_typescript_contract_is_current():
    assert OUTPUT.read_text(encoding="utf-8") == render_contracts()
