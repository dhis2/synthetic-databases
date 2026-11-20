"""Write metadata/categories.json: the category combos of an instance beside ANC and EIR.

* "Projects", an attribute combo of the options A, B and C, which ANC and EIR capture their events
  with (their programs' categoryCombo in anc.json and eir.json).
* 100 disaggregation combos "Age groups NNN and sex" of 10 age groups and Female, Male: 2,000
  category option combos no program or data element uses. Every tracker query checks the sharing
  of all their category options, and Postgres's estimate of that check grows with their number.

The metadata import generates no category option combos, and checks those it gets are a combo's
complete set: the file ships them all. UIDs derive from names, so a run writes the same file,
which tests/test_categories.py checks.

    uv run python databases/mnch/categories.py
"""

import itertools
import json
from pathlib import Path

from dbgen.uid import uid

OUT = Path(__file__).parent / "metadata" / "categories.json"

AGE_CATEGORIES = 100
AGE_GROUPS = 10
SEXES = ["Female", "Male"]
PROJECTS = ["A", "B", "C"]

# Options are readable and capturable by everyone; categories and combos have no data sharing, and
# get the packages' default. The rest of the sharing is DHIS2's default: owned by the importing
# admin, no user or user group access. So are the fields left out, such as skipTotal and
# ignoreApproval, which are false.
OPTION_SHARING = {"public": "r-rw----"}
SHARING = {"public": "rw------"}

# A category: its name and options.
Category = tuple[str, list[str]]


def ref(kind: str, name: str) -> dict:
    return {"id": uid(kind, name)}


def add_category(m: dict, name: str, options: list[str], dimension: str) -> Category:
    """Add a category and its options to the metadata m."""
    m["categoryOptions"].extend(
        {"id": uid("option", o), "name": o, "shortName": o, "sharing": OPTION_SHARING}
        for o in options
    )
    m["categories"].append(
        {
            "id": uid("category", name),
            "name": name,
            "shortName": name,
            "dataDimensionType": dimension,
            "dataDimension": False,
            "categoryOptions": [ref("option", o) for o in options],
            "sharing": SHARING,
        }
    )
    return name, options


def add_combo(m: dict, name: str, categories: list[Category], dimension: str) -> None:
    """Add a category combo and its option combos, one per combination of options, to m."""
    m["categoryCombos"].append(
        {
            "id": uid("combo", name),
            "name": name,
            "dataDimensionType": dimension,
            "categories": [ref("category", c) for c, _ in categories],
            "sharing": SHARING,
        }
    )
    m["categoryOptionCombos"].extend(
        {
            "id": uid("coc", f"{name}: {', '.join(options)}"),
            "name": ", ".join(options),
            "categoryCombo": ref("combo", name),
            "categoryOptions": [ref("option", o) for o in options],
        }
        for options in itertools.product(*(options for _, options in categories))
    )


def metadata() -> dict:
    m = {"categoryOptions": [], "categories": [], "categoryCombos": [], "categoryOptionCombos": []}
    projects = add_category(m, "Projects", PROJECTS, "ATTRIBUTE")
    add_combo(m, "Projects", [projects], "ATTRIBUTE")
    sex = add_category(m, "Sex", SEXES, "DISAGGREGATION")
    for k in range(1, AGE_CATEGORIES + 1):
        name = f"Age groups {k:03}"
        ages = add_category(
            m, name, [f"{name}, {j}" for j in range(1, AGE_GROUPS + 1)], "DISAGGREGATION"
        )
        add_combo(m, f"{name} and sex", [ages, sex], "DISAGGREGATION")
    ids = [o["id"] for objects in m.values() for o in objects]
    if len(ids) != len(set(ids)):
        raise SystemExit("categories: two objects got the same UID")
    return m


def render(m: dict) -> str:
    return json.dumps(m, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    m = metadata()
    OUT.write_text(render(m), encoding="utf-8")
    print(
        f"categories: wrote {OUT}: {len(m['categoryOptionCombos'])} category option combos, "
        f"{len(m['categoryCombos'])} combos, {len(m['categoryOptions'])} options"
    )


if __name__ == "__main__":
    main()
