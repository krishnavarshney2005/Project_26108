import pytest
from shared.models import Standard, StandardStatus, Evidence, InputType, Analysis
from kshiraj.knowledge.standards_store import StandardsStore
from kshiraj.knowledge.evidence_store import EvidenceStore
from kshiraj.bis_live_ingestion.sync import BISSyncService, SyncResult
from kartikey.orchestration.pipeline import _step_enrich

# ---------------------------------------------------------
# Mocks from original test_integration.py
# ---------------------------------------------------------
class MockBISClient:
    def __init__(self):
        from kshiraj.bis_live_ingestion.adapters.bis_client import BISClientConfig
        self.config = BISClientConfig()
        
    def search_standards(self, query: str):
        if query == "IS 1000:2015":
            return [{"standardNumber": "IS 1000:2015", "standardEncId": "enc123"}]
        if query == "IS 2000:2018":
            raise RuntimeError("Timeout connecting to BIS")
        return []
        
    def get_standard_details(self, enc_id: str):
        if enc_id == "enc123":
            return {
                "standardNumber": "IS 1000:2015",
                "standardId": "123",
                "statusName": "Active",
                "publishedOn": "2020-01-01",
                "superseded_byis": "IS 9999"
            }
        return {}
        
    def get_amendments(self, std_id: str):
        if std_id == "123":
            return [{"amendmentNumber": "1", "effectiveDate": "2021-01-01"}]
        return []

# ---------------------------------------------------------
# Mocks from test_integration2.py
# ---------------------------------------------------------
class MockBISClientTracker:
    def __init__(self):
        from kshiraj.bis_live_ingestion.adapters.bis_client import BISClientConfig
        self.config = BISClientConfig()
        self.calls = []
        
    def search_standards(self, query: str):
        self.calls.append(query)
        if query == "IS 1234 (Part 1/Sec 2):2020":
            return [{"standardNumber": "IS 1234 (Part 1/Sec 2):2020", "standardEncId": "enc1"}]
        if query == "IS 5678":
            return [{"standardNumber": "IS 5678", "standardEncId": "enc2"}]
        return [{"standardNumber": query, "standardEncId": "enc_any"}]
        
    def get_standard_details(self, enc_id: str):
        if enc_id == "enc1":
            return {"standardId": "id1", "standardNumber": "IS 1234 (Part 1/Sec 2):2020"}
        if enc_id == "enc2":
            return {"standardId": "id2", "standardNumber": "IS 5678", "supersheed": "IS 0000", "superseded_byis": "IS 9999"}
        return {"standardId": "id_any", "standardNumber": "IS 9999"}
        
    def get_amendments(self, std_id: str):
        return []


# ---------------------------------------------------------
# Tests
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_integration_enrich_preserves_derived_metadata():
    store = StandardsStore()
    offline_std = Standard(
        is_number="IS 1000",
        title="Mock offline title",
        year=2015,
        status=StandardStatus.UNKNOWN,
        scope="Offline Scope"
    )
    offline_std.semantic_score = 0.95
    store.add(offline_std)
    
    client = MockBISClient()
    service = BISSyncService(client, store)
    
    res = service.sync_designation("IS 1000:2015")
    assert not res.errors
    
    updated = store.get_by_id(offline_std.id)
    assert updated.status == StandardStatus.ACTIVE
    assert updated.scope == "Offline Scope"
    assert updated.semantic_score == 0.95
    assert updated.superseded_by == "IS 9999"
    assert len(updated.amendments) == 1
    assert updated.amendments[0].amendment_number == 1

@pytest.mark.asyncio
async def test_integration_bis_failure_non_fatal():
    store = StandardsStore()
    offline_std = Standard(
        is_number="IS 2000",
        title="Offline 2000",
        year=2018,
        status=StandardStatus.UNKNOWN
    )
    store.add(offline_std)
    
    client = MockBISClient()
    service = BISSyncService(client, store)
    
    res = service.sync_designation("IS 2000:2018")
    assert res.errors
    assert "Timeout connecting to BIS" in res.errors[0]
    
    updated = store.get_by_id(offline_std.id)
    assert updated.status == StandardStatus.UNKNOWN

@pytest.mark.asyncio
async def test_integration_exact_designation_and_evidence(monkeypatch):
    store = StandardsStore()
    ev_store = EvidenceStore()
    
    std = Standard(
        is_number="IS 1234",
        part="Part 1",
        section="Sec 2",
        year=2020,
        title="Complex Title",
        status=StandardStatus.UNKNOWN
    )
    store.add(std)
    
    analysis = Analysis(id="a1", input_type=InputType.TEXT, raw_text="", requirements=[])
    
    import kartikey.orchestration.knowledge_registry as kr
    class MockRegistry:
        standards_store = store
        evidence_store = ev_store
    monkeypatch.setattr(kr, "get_registry", lambda: MockRegistry())

    class MockAimlResponse:
        class MockFinding:
            verdict = "justified"
            applicable_standard_ids = [std.id]
        findings = [MockFinding()]
    
    import kartikey.orchestration.pipeline as p
    client_mock = MockBISClientTracker()
    monkeypatch.setattr("kshiraj.bis_live_ingestion.adapters.bis_client.BISClient", lambda: client_mock)
    
    await p._step_enrich(analysis, [std], MockAimlResponse())
    assert client_mock.calls == ["IS 1234 (Part 1/Sec 2):2020"]
    assert len(ev_store.list_all()) > 0

@pytest.mark.asyncio
async def test_integration_3_target_cap_and_ordinary_skip(monkeypatch):
    store = StandardsStore()
    ev_store = EvidenceStore()
    stds = []
    for i in range(5):
        s = Standard(is_number=f"IS {i}", title="T", status=StandardStatus.UNKNOWN)
        stds.append(s)
        store.add(s)
        
    ordinary = Standard(is_number="IS 999", title="T", status=StandardStatus.ACTIVE)
    stds.append(ordinary)
    store.add(ordinary)

    analysis = Analysis(id="a2", input_type=InputType.TEXT, raw_text="", requirements=[])
    
    import kartikey.orchestration.knowledge_registry as kr
    class MockRegistry:
        standards_store = store
        evidence_store = ev_store
    monkeypatch.setattr(kr, "get_registry", lambda: MockRegistry())

    client_mock = MockBISClientTracker()
    monkeypatch.setattr("kshiraj.bis_live_ingestion.adapters.bis_client.BISClient", lambda: client_mock)
    
    import kartikey.orchestration.pipeline as p
    await p._step_enrich(analysis, stds, None)
    
    assert len(client_mock.calls) == 3
    assert "IS 999" not in client_mock.calls

def test_supersession_direction():
    store = StandardsStore()
    std = Standard(is_number="IS 5678", title="T", status=StandardStatus.UNKNOWN)
    store.add(std)
    
    client = MockBISClientTracker()
    service = BISSyncService(client, store)
    service.sync_designation("IS 5678")
    
    updated = store.get_by_id(std.id)
    assert updated.superseded_by == "IS 9999"
    assert updated.superseded_by != "IS 0000"

