from pathlib import Path

import pytest

from pipeline import sqlfile


def test_statements_split_on_semicolons_outside_quotes_comments_and_dollar_bodies():
    text = """-- The file's header, which belongs to no statement.

-- First: a string with a semicolon.
select ';' as a, "odd;name" from t;

/* a block; comment */
select 1;
do $body$ begin perform 1; end $body$;
select $$;$$
"""
    found = sqlfile.statements(text)
    assert [s.sql for s in found] == [
        """select ';' as a, "odd;name" from t""",
        "/* a block; comment */\nselect 1",
        "do $body$ begin perform 1; end $body$",
        "select $$;$$",
    ]
    assert found[0].comment == "First: a string with a semicolon."
    assert found[0].title == "First"
    assert found[0].line == 4


def test_a_file_of_comments_holds_no_statements():
    assert sqlfile.statements("-- None yet.\n-- Each says why.\n") == []


@pytest.mark.parametrize("version", ["42", "43.0", "43", "dev"])
def test_the_upgrades_split_into_queries(version):
    path = Path(__file__).parents[1] / "upgrades" / version / "check.sql"
    for statement in sqlfile.statements(path.read_text()):
        assert statement.comment, f"{path}:{statement.line} says why it is there"
        assert statement.sql.split()[0] in ("select", "with"), statement.sql
