"""Job source connector contracts and development helpers."""

from ai_job_hunter.connectors.fake import FakeJobConnector
from ai_job_hunter.connectors.protocol import JobConnector

__all__ = ["FakeJobConnector", "JobConnector"]
