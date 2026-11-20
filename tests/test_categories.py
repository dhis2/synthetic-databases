import runpy
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "databases" / "mnch" / "categories.py"


def test_categories_json_is_what_the_script_writes():
    script = runpy.run_path(str(SCRIPT))
    written = script["OUT"].read_text(encoding="utf-8")
    assert written == script["render"](script["metadata"]()), (
        "metadata/categories.json is out of date: uv run python databases/mnch/categories.py"
    )
