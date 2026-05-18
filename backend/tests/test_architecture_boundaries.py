import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _collect_effect_names(value):
    names = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "effects":
                names.extend(item or [])
            else:
                names.extend(_collect_effect_names(item))
    elif isinstance(value, list):
        for item in value:
            names.extend(_collect_effect_names(item))
    return names


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_phase1_workflows_use_registered_effects_instead_of_write_hooks(self):
        from services.phase1_workflows import phase1_workflow_definitions
        from services.workflow_extensions import _EFFECTS, load_workflow_extensions

        source = (BACKEND / "services" / "phase1_workflows.py").read_text()
        self.assertNotIn("insert('", source)
        self.assertNotIn("update('", source)
        self.assertNotIn("_hook =", source)

        load_workflow_extensions()
        registered = {effect.name for effect in _EFFECTS}
        referenced = set()
        for definition in phase1_workflow_definitions():
            referenced.update(_collect_effect_names(definition))
        missing = sorted(referenced - registered)
        self.assertEqual(missing, [])

    def test_write_hooks_are_disabled_by_default(self):
        from services.hooks import validate_hook

        ok, message = validate_hook("insert('inventory', {'quantity': 1})")
        self.assertFalse(ok)
        self.assertIn("insert", message)

    def test_workflow_engine_has_no_wms_business_branching(self):
        source = (BACKEND / "services" / "workflow.py").read_text()
        forbidden = ["GOODS_RECEIPT", "SHIPMENT", "STOCKED_IN", "SALES_OUTBOUND", "services.wms"]
        found = [term for term in forbidden if term in source]
        self.assertEqual(found, [])

    def test_commands_register_domain_entrypoints(self):
        from services.command_registry import list_command_metadata

        metadata = {item["name"]: item for item in list_command_metadata()}
        names = set(metadata)
        expected = {
            "workflow_transition",
            "reserve_inventory",
            "release_reservation",
            "adjust_inventory_count",
            "create_accounts_receivable",
            "create_accounts_payable",
            "upsert_customer_credit",
        }
        self.assertTrue(expected <= names)
        self.assertTrue(metadata["create_accounts_receivable"]["supports_retry"])
        self.assertTrue(metadata["create_accounts_payable"]["supports_retry"])
        self.assertTrue(metadata["upsert_customer_credit"]["supports_retry"])

    def test_business_write_files_stay_inside_allowed_layers(self):
        allowed = {
            "backend/agents/admin_agent.py",
            "backend/agents/agent.py",
            "backend/routers/admin.py",
            "backend/services/commands.py",
            "backend/services/finance_commands.py",
            "backend/services/hooks.py",
            "backend/services/phase1_effects.py",
            "backend/services/wms.py",
            "backend/services/wms_commands.py",
            "backend/services/workflow.py",
        }
        patterns = [
            re.compile(r"\bdb\.add\("),
            re.compile(r"\bctx\.db\.add\("),
            re.compile(r"\bsync_session\.add\("),
            re.compile(r"\bawait db\.delete\("),
            re.compile(r"\bawait db\.commit\("),
            re.compile(r"\bawait ctx\.db\.commit\("),
            re.compile(r"\bsql_update\("),
        ]

        offenders = []
        for base in ("routers", "services", "agents"):
            for path in (BACKEND / base).rglob("*.py"):
                rel = path.relative_to(ROOT).as_posix()
                if rel in allowed:
                    continue
                source = path.read_text()
                if any(pattern.search(source) for pattern in patterns):
                    offenders.append(rel)
        self.assertEqual(sorted(offenders), [])

    def test_inventory_and_credit_commands_have_locks_and_inventory_movements(self):
        wms_commands = (BACKEND / "services" / "wms_commands.py").read_text()
        finance_commands = (BACKEND / "services" / "finance_commands.py").read_text()
        wms_domain = (BACKEND / "services" / "wms.py").read_text()

        self.assertIn("with_for_update()", wms_commands)
        self.assertIn("with_for_update()", finance_commands)
        self.assertIn("InventoryMovement", wms_commands + wms_domain)
        self.assertIn("existing", finance_commands)


if __name__ == "__main__":
    unittest.main()
