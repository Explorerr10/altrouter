from app.network.pingcheck import PingChecker
from app.network.segments import PingCheck


def make_checker(ping_results, renew_calls, log_calls, clock):
    queues = {iface: iter(seq) for iface, seq in ping_results.items()}

    def ping(iface, target):
        queue = queues.get(iface)
        return next(queue) if queue else (True, None)

    def renew(iface):
        renew_calls.append(iface)
        return True

    def logger(**extra):
        log_calls.append(extra)

    checker = PingChecker(ping=ping, renew=renew, logger=logger, clock=clock)
    checker.configure(
        {
            "enp5s0": PingCheck(enabled=True, target="1.1.1.1", interval_s=30, fail_threshold=2),
            "enp6s0": PingCheck(enabled=True, target="8.8.8.8", interval_s=30, fail_threshold=3),
        }
    )
    return checker


def test_ok_check_updates_state():
    renew, logs = [], []
    clock = [1000.0]
    checker = make_checker({"enp5s0": [(True, 12.5)]}, renew, logs, lambda: clock[0])
    checker.run_once()
    status = checker.status()
    assert status["enp5s0"]["state"] == "ok"
    assert status["enp5s0"]["latency_ms"] == 12.5
    assert status["enp5s0"]["fails"] == 0
    assert renew == [] and logs == []


def test_interval_respected():
    renew, logs = [], []
    clock = [1000.0]
    checker = make_checker({"enp5s0": [(True, 10.0), (True, 11.0)]}, renew, logs, lambda: clock[0])
    checker.run_once()
    clock[0] += 10  # меньше интервала 30
    checker.run_once()
    assert checker.status()["enp5s0"]["last_check"] == 1000.0


def tick(checker, clock, step=30):
    clock[0] += step
    checker.run_once()


def test_fail_threshold_triggers_renew_once():
    renew, logs = [], []
    clock = [1000.0]
    checker = make_checker(
        {"enp5s0": [(False, None), (False, None), (False, None)]},
        renew,
        logs,
        lambda: clock[0],
    )
    # enp5s0: threshold=2 → после двух неудач переподнятие, счётчик сбрасывается
    checker.run_once()
    tick(checker, clock)
    assert renew == ["enp5s0"]
    assert logs == [{"iface": "enp5s0"}]
    assert checker.status()["enp5s0"]["state"] == "fail"
    assert checker.status()["enp5s0"]["fails"] == 0
    # третья неудача: в пределах cooldown (60) — нового действия нет
    tick(checker, clock)
    assert renew == ["enp5s0"]
    assert checker.status()["enp5s0"]["fails"] == 1


def test_cooldown_expires_allows_new_action():
    renew, logs = [], []
    clock = [1000.0]
    checker = make_checker({"enp5s0": [(False, None)] * 4}, renew, logs, lambda: clock[0])
    checker.run_once()
    tick(checker, clock)
    assert renew == ["enp5s0"]
    tick(checker, clock, step=200)  # больше cooldown, но нужна серия из 2 неудач
    assert renew == ["enp5s0"]
    tick(checker, clock, step=200)
    assert renew == ["enp5s0", "enp5s0"]


def test_configure_drops_removed_policies():
    renew, logs = [], []
    checker = make_checker({}, renew, logs, lambda: 0.0)
    assert set(checker.status()) == {"enp5s0", "enp6s0"}
    checker.configure({})
    assert checker.status() == {}


def test_status_shape():
    renew, logs = [], []
    checker = make_checker({}, renew, logs, lambda: 0.0)
    item = checker.status()["enp6s0"]
    assert item["target"] == "8.8.8.8"
    assert item["interval_s"] == 30
    assert item["fail_threshold"] == 3
    assert item["state"] == "unknown"
    assert item["last_check"] is None
