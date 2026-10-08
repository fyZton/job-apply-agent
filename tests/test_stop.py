import pytest

from jobagent import core
from jobagent.core import StopRequested
from jobagent.safety import stop_requested


@pytest.fixture(autouse=True)
def no_hook():
    core.set_stop_check(None)
    yield
    core.set_stop_check(None)


def test_stop_requested_fails_closed_on_os_error(tmp_path, monkeypatch, caplog):
    def boom(self):
        raise PermissionError("denied")

    monkeypatch.setattr(type(tmp_path), "exists", boom)
    assert stop_requested(tmp_path) is True
    assert "STOP" in caplog.text


def test_check_stop_raises_only_when_the_hook_says_so():
    core.check_stop()  # no hook: nothing happens
    core.set_stop_check(lambda: False)
    core.check_stop()
    core.set_stop_check(lambda: True)
    with pytest.raises(StopRequested):
        core.check_stop()


def test_stop_requested_is_not_swallowed_by_except_exception():
    assert not issubclass(StopRequested, Exception)


def test_pause_polls_the_stop_file_while_waiting(monkeypatch):
    sleeps, polls = [], []
    clock = [0.0]
    monkeypatch.setattr(core.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(core.time, "sleep", lambda s: sleeps.append(s) or clock.__setitem__(0, clock[0] + s))

    def stop():
        polls.append(clock[0])
        return clock[0] >= 3

    core.set_stop_check(stop)
    with pytest.raises(StopRequested):
        core.pause(60, 60)
    assert sleeps and max(sleeps) <= 1.0 and clock[0] == 3


def test_pause_without_stop_waits_the_full_time(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(core.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(core.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    core.set_stop_check(lambda: False)
    core.pause(2.5, 2.5)
    assert clock[0] == pytest.approx(2.5)
