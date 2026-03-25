"""
Shared fixtures for all backend tests.
Loads the real graph_final.json so tests run against actual schema.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="session")
def graph_data() -> dict:
    return json.loads((DATA_DIR / "graph_final.json").read_text())


@pytest.fixture(scope="session")
def schema_data() -> dict:
    return json.loads((DATA_DIR / "normalized_schema.json").read_text())


@pytest.fixture(scope="session")
def graph_service(graph_data, schema_data):
    from app.models.graph import RawGraph
    from app.services.graph_service import GraphService

    raw = RawGraph(**graph_data)
    return GraphService(raw, schema=schema_data)


@pytest.fixture(scope="session")
def client(graph_service):
    from app.dependencies import init_service
    from app.main import app

    init_service(graph_service)
    return TestClient(app)
