"""Tests for US-064 Phase 2: /api/v1/graph/topology endpoint.

Covers:
    - Mock mode returns valid topology structure
    - Node extraction from pw-dump data
    - Link extraction with port resolution
    - GM managed annotation on nodes and links
    - SPA config internal topology attachment
    - Device extraction from GM state
    - Error handling when pw-dump fails
"""

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.graph_routes import (
    _attach_internal_topology,
    _extract_devices,
    _extract_links,
    _extract_nodes,
    _mock_topology,
)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_pw_data():
    """Minimal pw-dump JSON with 2 nodes, 2 ports, and 1 link."""
    return [
        {
            "id": 42,
            "type": "PipeWire:Interface:Node",
            "info": {
                "state": "running",
                "props": {
                    "node.name": "pi4audio-convolver",
                    "media.class": "Audio/Sink",
                    "node.description": "4-channel FIR convolver",
                },
            },
        },
        {
            "id": 55,
            "type": "PipeWire:Interface:Node",
            "info": {
                "state": "running",
                "props": {
                    "node.name": "Mixxx",
                    "media.class": "Stream/Output/Audio",
                },
            },
        },
        # Output port on Mixxx
        {
            "id": 200,
            "type": "PipeWire:Interface:Port",
            "info": {
                "props": {
                    "node.id": 55,
                    "port.name": "output_FL",
                    "port.direction": "out",
                },
            },
        },
        # Input port on convolver
        {
            "id": 201,
            "type": "PipeWire:Interface:Port",
            "info": {
                "props": {
                    "node.id": 42,
                    "port.name": "input_0",
                    "port.direction": "in",
                },
            },
        },
        # Link: Mixxx:output_FL -> convolver:input_0
        {
            "id": 300,
            "type": "PipeWire:Interface:Link",
            "info": {
                "output-node-id": 55,
                "output-port-id": 200,
                "input-node-id": 42,
                "input-port-id": 201,
                "state": "active",
            },
        },
        # Metadata object (not a node, should be ignored)
        {
            "id": 0,
            "type": "PipeWire:Interface:Metadata",
            "info": {
                "props": {"metadata.name": "settings"},
                "metadata": [],
            },
        },
    ]


@pytest.fixture
def sample_gm_state():
    """Minimal GM get_state response."""
    return {
        "ok": True,
        "mode": "dj",
        "nodes": ["pi4audio-convolver"],
        "links": [
            {
                "output_node": "Mixxx",
                "output_port": "output_FL",
                "input_node": "pi4audio-convolver",
                "input_port": "input_0",
            },
        ],
        "devices": {
            "convolver": "present",
            "usbstreamer": "present",
        },
    }


@pytest.fixture
def sample_spa_topology():
    """Minimal filter-chain internal topology from SPA config parser."""
    return {
        "nodes": [
            {"type": "builtin", "name": "convolver_left_hp",
             "label": "convolver_left_hp",
             "config": {"filename": "combined_left_hp.wav"}},
            {"type": "builtin", "name": "gain_left_hp",
             "label": "gain_left_hp",
             "control": {"Mult": 0.001}},
        ],
        "links": [
            {"output_node": "convolver_left_hp", "output_port": "Out",
             "input_node": "gain_left_hp", "input_port": "In"},
        ],
        "inputs": [
            {"node": "convolver_left_hp", "port": "In"},
        ],
        "outputs": [
            {"node": "gain_left_hp", "port": "Out"},
        ],
    }


# ── Mock endpoint tests ──────────────────────────────────────────

class TestMockTopology:
    def test_mock_returns_200(self, client):
        resp = client.get("/api/v1/graph/topology")
        assert resp.status_code == 200

    def test_mock_has_mode(self, client):
        data = client.get("/api/v1/graph/topology").json()
        assert data["mode"] == "dj"

    def test_mock_has_nodes(self, client):
        data = client.get("/api/v1/graph/topology").json()
        assert isinstance(data["nodes"], list)
        assert len(data["nodes"]) >= 1

    def test_mock_has_links(self, client):
        data = client.get("/api/v1/graph/topology").json()
        assert isinstance(data["links"], list)

    def test_mock_has_devices(self, client):
        data = client.get("/api/v1/graph/topology").json()
        assert isinstance(data["devices"], dict)

    def test_mock_convolver_node_has_id(self, client):
        data = client.get("/api/v1/graph/topology").json()
        convolver = [n for n in data["nodes"]
                     if n["name"] == "pi4audio-convolver"]
        assert len(convolver) == 1
        assert convolver[0]["id"] == 42

    def test_mock_convolver_has_internal(self, client):
        data = client.get("/api/v1/graph/topology").json()
        convolver = [n for n in data["nodes"]
                     if n["name"] == "pi4audio-convolver"][0]
        # internal topology depends on SPA config being available
        # In test env the repo config should be found
        if "internal" in convolver:
            assert "nodes" in convolver["internal"]
            assert "links" in convolver["internal"]

    def test_mock_node_shape(self, client):
        data = client.get("/api/v1/graph/topology").json()
        node = data["nodes"][0]
        assert "id" in node
        assert "name" in node
        assert "media_class" in node
        assert "state" in node
        assert "gm_managed" in node

    def test_mock_link_shape(self, client):
        data = client.get("/api/v1/graph/topology").json()
        if data["links"]:
            link = data["links"][0]
            assert "id" in link
            assert "output_node" in link
            assert "output_port" in link
            assert "input_node" in link
            assert "input_port" in link
            assert "state" in link
            assert "gm_managed" in link


# ── Node extraction tests ────────────────────────────────────────

class TestExtractNodes:
    def test_extracts_two_nodes(self, sample_pw_data):
        nodes = _extract_nodes(sample_pw_data, None)
        assert len(nodes) == 2

    def test_ignores_non_node_objects(self, sample_pw_data):
        nodes = _extract_nodes(sample_pw_data, None)
        types = {n["name"] for n in nodes}
        assert "settings" not in types

    def test_node_fields(self, sample_pw_data):
        nodes = _extract_nodes(sample_pw_data, None)
        convolver = [n for n in nodes if n["name"] == "pi4audio-convolver"][0]
        assert convolver["id"] == 42
        assert convolver["media_class"] == "Audio/Sink"
        assert convolver["state"] == "running"
        assert convolver["description"] == "4-channel FIR convolver"

    def test_gm_managed_true_when_in_state(self, sample_pw_data, sample_gm_state):
        nodes = _extract_nodes(sample_pw_data, sample_gm_state)
        convolver = [n for n in nodes if n["name"] == "pi4audio-convolver"][0]
        assert convolver["gm_managed"] is True

    def test_gm_managed_false_when_not_in_state(self, sample_pw_data, sample_gm_state):
        nodes = _extract_nodes(sample_pw_data, sample_gm_state)
        mixxx = [n for n in nodes if n["name"] == "Mixxx"][0]
        assert mixxx["gm_managed"] is False

    def test_no_gm_state_means_all_unmanaged(self, sample_pw_data):
        nodes = _extract_nodes(sample_pw_data, None)
        assert all(not n["gm_managed"] for n in nodes)

    def test_no_description_omitted(self, sample_pw_data):
        nodes = _extract_nodes(sample_pw_data, None)
        mixxx = [n for n in nodes if n["name"] == "Mixxx"][0]
        assert "description" not in mixxx


# ── Link extraction tests ────────────────────────────────────────

class TestExtractLinks:
    def test_extracts_one_link(self, sample_pw_data):
        links = _extract_links(sample_pw_data, None)
        assert len(links) == 1

    def test_link_resolves_port_names(self, sample_pw_data):
        links = _extract_links(sample_pw_data, None)
        link = links[0]
        assert link["output_port"] == "output_FL"
        assert link["input_port"] == "input_0"

    def test_link_resolves_node_ids(self, sample_pw_data):
        links = _extract_links(sample_pw_data, None)
        link = links[0]
        assert link["output_node"] == 55
        assert link["input_node"] == 42

    def test_link_state(self, sample_pw_data):
        links = _extract_links(sample_pw_data, None)
        assert links[0]["state"] == "active"

    def test_link_id(self, sample_pw_data):
        links = _extract_links(sample_pw_data, None)
        assert links[0]["id"] == 300

    def test_gm_managed_link(self, sample_pw_data, sample_gm_state):
        links = _extract_links(sample_pw_data, sample_gm_state)
        assert links[0]["gm_managed"] is True

    def test_unmanaged_link(self, sample_pw_data):
        links = _extract_links(sample_pw_data, None)
        assert links[0]["gm_managed"] is False


# ── Device extraction tests ───────────────────────────────────────

class TestExtractDevices:
    def test_with_gm_state(self, sample_gm_state):
        devices = _extract_devices(sample_gm_state)
        assert devices["convolver"] == "present"
        assert devices["usbstreamer"] == "present"

    def test_without_gm_state(self):
        devices = _extract_devices(None)
        assert devices == {}


# ── Internal topology attachment ──────────────────────────────────

class TestAttachInternalTopology:
    def test_attaches_to_convolver(self, sample_spa_topology):
        nodes = [
            {"name": "pi4audio-convolver", "id": 42},
            {"name": "Mixxx", "id": 55},
        ]
        _attach_internal_topology(nodes, sample_spa_topology)
        assert "internal" in nodes[0]
        assert nodes[0]["internal"] == sample_spa_topology

    def test_no_attachment_to_other_nodes(self, sample_spa_topology):
        nodes = [
            {"name": "pi4audio-convolver", "id": 42},
            {"name": "Mixxx", "id": 55},
        ]
        _attach_internal_topology(nodes, sample_spa_topology)
        assert "internal" not in nodes[1]

    def test_no_topology_no_change(self):
        nodes = [{"name": "pi4audio-convolver", "id": 42}]
        _attach_internal_topology(nodes, None)
        assert "internal" not in nodes[0]

    def test_no_convolver_node_no_error(self, sample_spa_topology):
        nodes = [{"name": "Mixxx", "id": 55}]
        _attach_internal_topology(nodes, sample_spa_topology)
        assert "internal" not in nodes[0]


# ── Production path tests (mocked) ───────────────────────────────

class TestProductionPath:
    @patch("app.graph_routes.MOCK_MODE", False)
    @patch("app.graph_routes.pw_dump", new_callable=AsyncMock)
    def test_pw_dump_failure_returns_502(self, mock_pw_dump, client):
        mock_pw_dump.return_value = None
        resp = client.get("/api/v1/graph/topology")
        assert resp.status_code == 502
        assert resp.json()["error"] == "pw_dump_failed"

    @patch("app.graph_routes.MOCK_MODE", False)
    @patch("app.graph_routes.pw_dump", new_callable=AsyncMock)
    @patch("app.graph_routes._read_spa_topology")
    def test_pw_dump_success_returns_topology(
        self, mock_spa, mock_pw_dump, client, sample_pw_data, sample_gm_state,
    ):
        mock_pw_dump.return_value = sample_pw_data
        mock_spa.return_value = None

        # Simulate GM state on the app.state.cdsp collector
        class FakeCollector:
            _state = sample_gm_state
        with patch.object(app.state, "cdsp", FakeCollector(), create=True):
            resp = client.get("/api/v1/graph/topology")

        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "dj"
        assert len(data["nodes"]) == 2
        assert len(data["links"]) == 1
        assert data["devices"]["convolver"] == "present"

    @patch("app.graph_routes.MOCK_MODE", False)
    @patch("app.graph_routes.pw_dump", new_callable=AsyncMock)
    @patch("app.graph_routes._read_spa_topology")
    def test_no_gm_collector_uses_none(
        self, mock_spa, mock_pw_dump, client, sample_pw_data,
    ):
        mock_pw_dump.return_value = sample_pw_data
        mock_spa.return_value = None

        # Remove cdsp from app.state if present
        if hasattr(app.state, "cdsp"):
            delattr(app.state, "cdsp")

        resp = client.get("/api/v1/graph/topology")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "unknown"
        assert all(not n["gm_managed"] for n in data["nodes"])

    @patch("app.graph_routes.MOCK_MODE", False)
    @patch("app.graph_routes.pw_dump", new_callable=AsyncMock)
    @patch("app.graph_routes._read_spa_topology")
    def test_spa_topology_attached_to_convolver(
        self, mock_spa, mock_pw_dump, client,
        sample_pw_data, sample_spa_topology,
    ):
        mock_pw_dump.return_value = sample_pw_data
        mock_spa.return_value = sample_spa_topology

        if hasattr(app.state, "cdsp"):
            delattr(app.state, "cdsp")

        resp = client.get("/api/v1/graph/topology")
        assert resp.status_code == 200
        data = resp.json()
        convolver = [n for n in data["nodes"]
                     if n["name"] == "pi4audio-convolver"][0]
        assert "internal" in convolver
        assert len(convolver["internal"]["nodes"]) == 2


# ── Mock topology function tests ──────────────────────────────────

class TestMockTopologyFunction:
    def test_returns_dict(self):
        result = _mock_topology()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = _mock_topology()
        assert "mode" in result
        assert "nodes" in result
        assert "links" in result
        assert "devices" in result

    def test_nodes_have_required_fields(self):
        result = _mock_topology()
        for node in result["nodes"]:
            assert "id" in node
            assert "name" in node
            assert "media_class" in node
            assert "state" in node
            assert "gm_managed" in node

    def test_links_have_required_fields(self):
        result = _mock_topology()
        for link in result["links"]:
            assert "id" in link
            assert "output_node" in link
            assert "output_port" in link
            assert "input_node" in link
            assert "input_port" in link
            assert "state" in link
            assert "gm_managed" in link
