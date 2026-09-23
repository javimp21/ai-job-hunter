from ai_job_hunter.connectors import FakeJobConnector, JobConnector
from ai_job_hunter.domain.normalized_job import NormalizedJob


def test_fake_connector_implements_contract_and_replays_offers(fake_offer_batch) -> None:
    connector = FakeJobConnector(fake_offer_batch)

    assert isinstance(connector, JobConnector)
    assert tuple(connector.fetch_jobs()) == fake_offer_batch
    assert tuple(connector.fetch_jobs()) == fake_offer_batch
    assert all(isinstance(offer, NormalizedJob) for offer in connector.fetch_jobs())
