"""Job source connector contracts and development helpers."""

from ai_job_hunter.connectors.fake import FakeJobConnector
from ai_job_hunter.connectors.ashby import AshbyConnector, AshbyConnectorError
from ai_job_hunter.connectors.factory import build_job_connectors
from ai_job_hunter.connectors.greenhouse import GreenhouseConnector, GreenhouseConnectorError
from ai_job_hunter.connectors.lever import LeverConnector, LeverConnectorError
from ai_job_hunter.connectors.protocol import JobConnector
from ai_job_hunter.connectors.remotive import RemotiveConnector, RemotiveConnectorError

from ai_job_hunter.connectors.smartrecruiters import (
    SmartRecruitersConnector,
    SmartRecruitersConnectorError,
)
from ai_job_hunter.connectors.teamtailor import TeamtailorConnector, TeamtailorConnectorError
from ai_job_hunter.connectors.factorial import FactorialConnector, FactorialConnectorError
from ai_job_hunter.connectors.personio import PersonioConnector, PersonioConnectorError
from ai_job_hunter.connectors.workday import WorkdayConnector, WorkdayConnectorError
from ai_job_hunter.connectors.workable import WorkableConnector, WorkableConnectorError

__all__ = [
    "FactorialConnector",
    "FactorialConnectorError",
    "WorkdayConnector",
    "WorkdayConnectorError",
    "PersonioConnector",
    "PersonioConnectorError",
    "WorkableConnector",
    "WorkableConnectorError",
    "SmartRecruitersConnector",
    "SmartRecruitersConnectorError",
    "TeamtailorConnector",
    "TeamtailorConnectorError",
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
