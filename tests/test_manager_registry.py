import json
from pathlib import Path


root = Path(__file__).resolve().parents[1]
registry_path = root / "addons" / "Faidlix_Manager" / "addon_registry.json"
index_path = root / "repository" / "index.json"

registry = json.loads(registry_path.read_text(encoding="utf-8"))
index = json.loads(index_path.read_text(encoding="utf-8"))

assert registry["schema_version"] == 1
entries = registry["addons"]
package_ids = [entry["package_id"] for entry in entries]
assert len(package_ids) == len(set(package_ids))
assert "faidlix_manager" in package_ids
assert all("update_all" in entry["common_features"] for entry in entries)

published_ids = {item["id"] for item in index["data"]}
assert set(package_ids) == published_ids

legacy_helpers = list((root / "addons").glob("*/_faidlix_update_all.py"))
assert not legacy_helpers, legacy_helpers
print("FAIDLIX_MANAGER_REGISTRY=PASS")
