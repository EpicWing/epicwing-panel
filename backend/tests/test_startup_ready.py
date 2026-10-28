"""Ein Server mit "done"-Text im Egg gilt erst als laufend, wenn die Konsole ihn zeigt."""

import json

from app.services.server_state import next_status
from app.services.startup_ready import FALLBACK_SECONDS, ReadyWatcher, done_texts

CONFIG = json.dumps({"startup": json.dumps({"done": "Loading level: 100%"})})


def test_done_text_from_json_string_dict_and_list():
    assert done_texts(CONFIG) == ("Loading level: 100%",)
    assert done_texts(json.dumps({"startup": {"done": "ready"}})) == ("ready",)
    assert done_texts(json.dumps({"startup": {"done": ["a", "", 3, "b"]}})) == ("a", "b")


def test_no_done_text_means_old_behavior():
    for config in ("{}", "", "kaputt", "[]", json.dumps({"startup": "kaputt"})):
        assert done_texts(config) == ()
    assert next_status("starting", "running", None) == ("running", None)


def test_hold_keeps_starting_until_console_says_ready():
    assert next_status("starting", "running", None, True) == (None, None)
    assert next_status("offline", "running", None, True) == ("starting", None)
    assert next_status("running", "running", None, True) == (None, None)
    assert next_status("starting", "exited", 1, True)[0] == "error"


def test_watcher_detects_done_text_across_chunks():
    w = ReadyWatcher()
    w.watch("a", ("Loading level: 100%",), 0.0)
    assert not w.feed("a", "Loading level: 9")
    assert not w.feed("a", "4%\n")
    assert w.feed("a", "Loading level: 1")is False
    assert w.feed("a", "00%\n")
    assert not w.watching("a")
    assert not w.feed("a", "Loading level: 100%")


def test_watcher_fallback_after_timeout():
    w = ReadyWatcher()
    w.watch("a", ("x",), 100.0)
    assert not w.expired("a", 100.0 + FALLBACK_SECONDS - 1)
    assert w.expired("a", 100.0 + FALLBACK_SECONDS)
    w.forget("a")
    assert not w.expired("a", 10_000.0)
