import pytest

from app.services import rules


@pytest.mark.parametrize(
    ("value", "rule_text", "expected"),
    [
        ("20", "required|integer|between:1,100", None),
        ("0", "required|integer|between:1,100", "Must be between 1 and 100."),
        ("abc", "required|integer|between:1,100", "Must be a whole number."),
        ("", "required", "A value is required."),
        ("", "nullable|integer", None),
        ("ab", "max:3", None),
        ("abcd", "max:3", "Must be at most 3 characters."),
        ("a", "min:2", "Must be at least 2 characters."),
        ("5", "integer|min:10", "Must be at least 10."),
        ("x", "in:a,b", "Must be one of: a, b."),
        ("a", "not_in:a,b", "This value is not allowed."),
        ("a_b-1", "alpha_dash", None),
        ("a b", "alpha_num", "May only contain letters and digits."),
        ("true", "boolean", None),
        ("yes", "boolean", "Must be true or false."),
        ("1.5", "numeric|max:2", None),
        ("server.jar", r"required|regex:/^[\w.]+\.jar$/", None),
        ("server.txt", r"regex:/^[\w.]+\.jar$/", "The format is invalid."),
        ("ABC", "regex:/^abc$/i", None),
    ],
)
def test_validate(value, rule_text, expected):
    assert rules.validate(value, rule_text) == expected


@pytest.mark.parametrize(
    ("rule_text", "expected"),
    [
        ("required|integer|between:1,100", []),
        ("required|regex:/^a|b$/", []),
        ("bogus", ["Unknown rule: bogus."]),
        ("min", ["The rule min needs one number."]),
        ("between:5,1", ["The rule between needs two numbers, the smaller one first."]),
        ("required:1", ["The rule required takes no value."]),
        ("in", ["The rule in needs a list of values."]),
        ("regex:/(/", ["The regex of the rule is invalid."]),
        ("x" * 600, ["The rules may have at most 512 characters."]),
    ],
)
def test_problems(rule_text, expected):
    assert rules.problems(rule_text) == expected


def test_drop_unknown_keeps_only_usable_rules():
    kept, dropped = rules.drop_unknown("required|integer|url|max:abc")
    assert (kept, dropped) == ("required|integer", ["url", "max"])
    assert rules.drop_unknown("") == ("", [])
