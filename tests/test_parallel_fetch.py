import threading
import time
from uuid import uuid4

import pytest

from ai_job_hunter.domain.company_intelligence import ATSDiscoveryConfidence, ATSProvider, CompanyMonitorTarget
from ai_job_hunter.job_sources import JobSourceSpec
from ai_job_hunter.services import opportunities


def target(name, provider, identifier):
    return CompanyMonitorTarget(
        company_id=uuid4(), company_name=name, provider=provider, identifier=identifier,
        careers_url=f"https://{identifier}.example.test", evidence_source="test", confidence=ATSDiscoveryConfidence.DIRECT_URL_PATTERN,
    )


class Probe:
    """A fake connector that records how many reads of its server overlap in time."""

    def __init__(self, name, active, peak, lock, barrier=None, delay=0.0, fail=False):
        self.name, self.active, self.peak, self.lock = name, active, peak, lock
        self.barrier, self.delay, self.fail = barrier, delay, fail

    def fetch_jobs(self):
        with self.lock:
            self.active[self.name] = self.active.get(self.name, 0) + 1
            self.peak[self.name] = max(self.peak.get(self.name, 0), self.active[self.name])
        try:
            if self.barrier is not None:
                self.barrier.wait(timeout=5)  # only passes when the others run at the same moment
            time.sleep(self.delay)
            if self.fail:
                raise opportunities.GreenhouseConnectorError("boom")
            return []
        finally:
            with self.lock:
                self.active[self.name] -= 1


def run_fetch(monkeypatch, targets, probes, workers=8):
    monkeypatch.setattr(opportunities, "build_job_connectors", lambda config, **kw: probes)

    class Settings:
        fetch_workers = workers

    monkeypatch.setattr(opportunities, "get_settings", lambda: Settings())
    return opportunities._fetch_targets(targets, max_jobs_per_company=50, client=object())


def test_boards_of_different_servers_are_read_at_the_same_time(monkeypatch):
    barrier = threading.Barrier(3)
    lock, active, peak = threading.Lock(), {}, {}
    targets = [
        target("A", ATSProvider.TEAMTAILOR, "a"), target("B", ATSProvider.PERSONIO, "b"), target("C", ATSProvider.RECRUITEE, "c"),
    ]
    probes = [Probe(t.company_name, active, peak, lock, barrier=barrier) for t in targets]

    offers, failures = run_fetch(monkeypatch, targets, probes)

    # Sequential reading would never fill the barrier (each wait would time out and raise).
    assert offers == [] and failures == []


def test_a_server_is_never_read_with_more_connections_than_its_limit(monkeypatch):
    lock, active, peak = threading.Lock(), {}, {}
    lever = [target(f"L{i}", ATSProvider.LEVER, f"l{i}") for i in range(4)]
    greenhouse = [target(f"G{i}", ATSProvider.GREENHOUSE, f"g{i}") for i in range(8)]
    targets = lever + greenhouse
    probes = []
    for t in lever:
        probes.append(Probe("lever", active, peak, lock, delay=0.03))
    for t in greenhouse:
        probes.append(Probe("greenhouse", active, peak, lock, delay=0.03))

    run_fetch(monkeypatch, targets, probes)

    assert peak["lever"] == 1  # Lever blocks aggressive clients
    assert 2 <= peak["greenhouse"] <= opportunities.HOST_CONCURRENCY["greenhouse"]


def test_failures_are_reported_per_board_and_the_other_boards_are_still_read(monkeypatch):
    lock, active, peak = threading.Lock(), {}, {}
    targets = [target("Good", ATSProvider.GREENHOUSE, "good"), target("Bad", ATSProvider.GREENHOUSE, "bad")]
    probes = [Probe("x", active, peak, lock), Probe("y", active, peak, lock, fail=True)]

    offers, failures = run_fetch(monkeypatch, targets, probes)

    assert [(f.company, f.error_type) for f in failures] == [("Bad", "GreenhouseConnectorError")]


def test_boards_not_started_before_the_deadline_are_skipped_as_failed(monkeypatch):
    monkeypatch.setattr(opportunities, "FETCH_DEADLINE_SECONDS", -1)
    lock, active, peak = threading.Lock(), {}, {}
    targets = [target("Late", ATSProvider.GREENHOUSE, "late")]

    offers, failures = run_fetch(monkeypatch, targets, [Probe("late", active, peak, lock)])

    assert [(f.company, f.error_type) for f in failures] == [("Late", "FetchDeadlineReached")] and peak == {}
