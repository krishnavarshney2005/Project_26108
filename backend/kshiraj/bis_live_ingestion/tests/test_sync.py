import httpx

from kshiraj.bis_live_ingestion.adapters.bis_client import BISClient, BISClientConfig
from kshiraj.bis_live_ingestion.sync import BISSyncService
from kshiraj.knowledge.standards_store import StandardsStore


def test_sync_designation_upserts_live_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("searchKnowStandards"):
            return httpx.Response(200, json={"status": "SUCCESS", "data": [{
                "standardNumber": "IS 694:2010", "standardEncId": "opaque-123"
            }]})
        if request.url.path.endswith("getWebsiteStandardDetails"):
            return httpx.Response(200, json={"status": "SUCCESS", "data": {
                "standardId": 123,
                "standardNumber": "IS 694:2010",
                "standardName": "PVC insulated cables",
                "publishedOn": "2010-01-01",
                "withdrawStatus": 0,
                "status": "ACTIVE",
            }})
        if request.url.path.endswith("getAmendmentDetails"):
            return httpx.Response(200, json={"status": "SUCCESS", "data": [
                {"noOfAmendment": 1, "amendmentYear": "2012", "amendmentLabel": "Cable amendment"}
            ]})
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = BISClient(BISClientConfig(max_retries=0), client=http)
        result = BISSyncService(client, StandardsStore()).sync_designation("IS 694:2010")

    assert result.errors == []
    assert result.amendment_count == 1
    assert result.matched_designation == "IS 694:2010"
    assert len(result.evidence) == 2
