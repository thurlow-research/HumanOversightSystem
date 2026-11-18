"""Mutation-driven gap tests for human_authorization.decide (TD-2101 §7.1 hardening). Pure."""

from __future__ import annotations

import pytest

from tests.framework.test_human_authorization_predicate import T1, T2, _c, _decide, _form, _reasons


def test_bot_typed_actor_without_bot_suffix_is_refused_as_bot():
    v = _decide([_c(1, "scottthurlow", type="Bot", body=_form())])
    assert _reasons(v) == ["bot-actor"]
    assert v.authorized is False


def test_unmet_verdict_authorized_is_the_false_singleton():
    v = _decide([])
    assert v.authorized is False and v.covered == () and v.accepted is None


@pytest.mark.parametrize(
    "kwargs,fragment",
    [
        ({"co": frozenset()}, "codeowners"),
        ({"bots": frozenset()}, "bots"),
        ({"required": ()}, "required_items"),
        ({"binding": "patch:xyz"}, "binding"),
    ],
)
def test_precondition_message_names_the_offending_argument(kwargs, fragment):
    with pytest.raises(ValueError, match=fragment):
        _decide([], **kwargs)


def test_empty_login_never_authorizes_even_with_valid_form():
    v = _decide([_c(1, "", type="User", body=_form())])
    assert v.authorized is False and _reasons(v) == ["not-codeowner"]


def test_edited_authorize_after_valid_act_is_refused_but_older_act_does_not_govern():
    v = _decide(
        [
            _c(1, "scottthurlow", created=T1, body=_form()),
            _c(2, "scottthurlow", created=T2, updated="2026-10-20T13:00:00Z", body=_form()),
        ]
    )
    assert v.authorized is False
    assert "edited" in _reasons(v)


def test_accepted_act_is_not_reported_as_a_refusal_and_governing_is_the_act():
    v = _decide([_c(1, "scottthurlow", body=_form())])
    assert v.authorized and v.refusals == ()
    assert v.accepted.overlap == ("docs/y.md", "scripts/x.py")
