import json
from pathlib import Path


root = Path(__file__).resolve().parents[1]
readme = (root / "README.md").read_text(encoding="utf-8")
index = json.loads((root / "repository" / "index.json").read_text(encoding="utf-8"))
raw_base = "https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/"

for item in index["data"]:
    archive_name = item["archive_url"].removeprefix("./")
    archive_path = root / "repository" / archive_name
    expected_label = f"[{item['name']} {item['version']}]"
    expected_link = f"]({raw_base}{archive_name})"
    assert archive_path.is_file(), archive_path
    assert expected_label in readme, expected_label
    assert expected_link in readme, expected_link

print("README_DOWNLOAD_LINKS=PASS")
