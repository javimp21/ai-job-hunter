"""Job source connector contracts and development helpers."""

from ai_job_hunter.connectors.fake import FakeJobConnector
from ai_job_hunter.connectors.ashby import AshbyConnector, AshbyConnectorError
from ai_job_hunter.connectors.factory import build_job_connectors
from ai_job_hunter.connectors.greenhouse import GreenhouseConnector, GreenhouseConnectorError
from ai_job_hunter.connectors.lever import LeverConnector, LeverConnectorError
from ai_job_hunter.connectors.protocol import JobConnector
from ai_job_hunter.connectors.remotive import RemotiveConnector, RemotiveConnectorError

__all__ = [
    "FakeJobConnector",
    "AshbyConnector",
    "AshbyConnectorError",
    "build_job_connectors",
    "GreenhouseConnector",
    "GreenhouseConnectorError",
    "JobConnector",
    "LeverConnector",
    "LeverConnectorError",
    "RemotiveConnector",
    "RemotiveConnectorError",
]
