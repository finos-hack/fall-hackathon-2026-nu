import pytest

from agip_shared.contracts import HumanTask
from agip_shared.humantasks import (
    HumanTaskStore, InvalidTaskTransition, NotAuthorized, ResumeCallbacks,
    TaskExists, TaskNotFound, TRANSITIONS, load_roles,
)

ALL_STATES = ["OPEN", "ASSIGNED", "CLAIMED", "COMPLETED", "REJECTED", "CHANGES_REQUESTED", "CANCELLED"]
ALL_ACTIONS = ["ASSIGN", "CLAIM", "COMPLETE", "REJECT", "REQUEST_CHANGES", "CANCEL"]


def mk(tid="t1", **kw):
    base = dict(task_id=tid, framework="rule_authoring", task_type="RULE_REVIEW",
                subject_refs=["rule:1"], role="rule_reviewer",
                permitted_actions=ALL_ACTIONS)
    base.update(kw)
    return HumanTask(**base)


@pytest.fixture
def store(tmp_path):
    return HumanTaskStore(tmp_path, callbacks=ResumeCallbacks())


def drive(store, tid, state):
    """Bring a fresh task to the given state via valid actions."""
    path = {"OPEN": [], "ASSIGNED": ["ASSIGN"], "CLAIMED": ["CLAIM"], "COMPLETED": ["CLAIM", "COMPLETE"],
            "REJECTED": ["CLAIM", "REJECT"], "CHANGES_REQUESTED": ["CLAIM", "REQUEST_CHANGES"],
            "CANCELLED": ["CANCEL"]}[state]
    for a in path:
        store.act(tid, "alice", "rule_reviewer", a, "r")


def test_create_get_duplicate_missing(store):
    store.create(mk())
    assert store.get("t1").status == "OPEN"
    with pytest.raises(TaskExists):
        store.create(mk())
    with pytest.raises(TaskNotFound):
        store.get("nope")


def test_list_filters(store):
    store.create(mk("a", priority="HIGH", trace_id="tr1"))
    store.create(mk("b", framework="calm_generation", task_type="PATTERN_APPROVAL", role="architect",
                    subject_refs=["app:x"], context={"app": "app-9"}))
    store.act("a", "bob", "rule_reviewer", "CLAIM", "r")
    ids = lambda **kw: sorted(t.task_id for t in store.list(**kw))
    assert ids() == ["a", "b"]
    assert ids(framework="calm_generation") == ["b"]
    assert ids(task_type="RULE_REVIEW") == ["a"]
    assert ids(status="CLAIMED") == ["a"]
    assert ids(role="architect") == ["b"]
    assert ids(actor="bob") == ["a"]
    assert ids(priority="HIGH") == ["a"]
    assert ids(trace_id="tr1") == ["a"]
    assert ids(subject_ref="app:x") == ["b"]
    assert ids(app="app-9") == ["b"]
    assert ids(status="OPEN", framework="rule_authoring") == []


@pytest.mark.parametrize("state", ALL_STATES)
@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_every_transition(tmp_path, state, action):
    s = HumanTaskStore(tmp_path / f"{state}-{action}", callbacks=ResumeCallbacks())
    s.create(mk())
    drive(s, "t1", state)
    expected = TRANSITIONS[action].get(state)
    if expected:
        o = s.act("t1", "carol", "rule_reviewer", action, "why")
        assert (o.previous_state, o.resulting_state) == (state, expected)
        assert s.get("t1").status == expected
    else:
        with pytest.raises(InvalidTaskTransition):
            s.act("t1", "carol", "rule_reviewer", action, "why")
        assert s.get("t1").status == state


def test_spec_transitions_exact():
    assert TRANSITIONS["ASSIGN"] == {"OPEN": "ASSIGNED"}
    assert set(TRANSITIONS["CANCEL"]) == {"OPEN", "ASSIGNED", "CLAIMED", "CHANGES_REQUESTED"}


def test_unauthorized_role(store):
    store.create(mk())
    with pytest.raises(NotAuthorized):
        store.act("t1", "x", "random_role", "CLAIM", "r")
    assert store.outcomes("t1") == []


def test_action_not_permitted(store):
    store.create(mk(permitted_actions=["CLAIM"]))
    store.act("t1", "x", "rule_reviewer", "CLAIM", "r")
    with pytest.raises(NotAuthorized):
        store.act("t1", "x", "rule_reviewer", "COMPLETE", "r")


def test_self_approval_refused(store):
    store.create(mk(context={"created_by": "dave"}))
    store.act("t1", "dave", "rule_reviewer", "CLAIM", "r")
    with pytest.raises(NotAuthorized):
        store.act("t1", "dave", "rule_reviewer", "COMPLETE", "r")
    assert store.get("t1").status == "CLAIMED"
    store.act("t1", "erin", "rule_reviewer", "COMPLETE", "r")
    assert store.get("t1").status == "COMPLETED"


def test_roles_yaml_override(tmp_path):
    p = tmp_path / "roles.json"  # JSON is valid YAML
    p.write_text('{"RULE_REVIEW": ["special"]}', encoding="utf-8")
    s = HumanTaskStore(tmp_path / "d", roles_path=p, callbacks=ResumeCallbacks())
    s.create(mk())
    with pytest.raises(NotAuthorized):
        s.act("t1", "x", "rule_reviewer", "CLAIM", "r")
    s.act("t1", "x", "special", "CLAIM", "r")
    assert "PATTERN_APPROVAL" in load_roles(p)


def test_outcomes_append_only_and_immutable(store):
    store.create(mk())
    store.act("t1", "a", "rule_reviewer", "CLAIM", "first")
    f = store._p("t1", ".outcomes.jsonl")
    before = f.read_bytes()
    o = store.act("t1", "a", "rule_reviewer", "REQUEST_CHANGES", "second")
    after = f.read_bytes()
    assert after.startswith(before) and len(after) > len(before)
    assert len(store.outcomes("t1")) == 2
    with pytest.raises(Exception):
        o.rationale = "tampered"
    assert not any(hasattr(store, n) for n in ("update_outcome", "delete_outcome", "rewrite_outcome"))
    store.act("t1", "a", "rule_reviewer", "CLAIM", "third")
    assert [x.rationale for x in store.outcomes("t1")] == ["first", "second", "third"]


def test_restart_persistence(tmp_path):
    s1 = HumanTaskStore(tmp_path, callbacks=ResumeCallbacks())
    s1.create(mk())
    s1.act("t1", "a", "rule_reviewer", "CLAIM", "r", outcome_artifact_id="art-1")
    s2 = HumanTaskStore(tmp_path, callbacks=ResumeCallbacks())
    assert s2.get("t1").status == "CLAIMED"
    assert [t.task_id for t in s2.list()] == ["t1"]
    outs = s2.outcomes("t1")
    assert len(outs) == 1 and outs[0].outcome_artifact_id == "art-1"


def test_resume_callbacks(tmp_path):
    cb, seen = ResumeCallbacks(), []
    cb.register("RULE_REVIEW", lambda t, o: seen.append(o.resulting_state))
    s = HumanTaskStore(tmp_path, callbacks=cb)
    s.create(mk("a")); s.create(mk("b")); s.create(mk("c"))
    s.act("a", "x", "rule_reviewer", "CLAIM", "r"); s.act("a", "x", "rule_reviewer", "COMPLETE", "r")
    s.act("b", "x", "rule_reviewer", "CLAIM", "r"); s.act("b", "x", "rule_reviewer", "REJECT", "r")
    s.act("c", "x", "rule_reviewer", "CANCEL", "r")
    assert seen == ["COMPLETED", "REJECTED"]


def test_bad_task_id(store):
    with pytest.raises(Exception):
        store.get("../evil")
