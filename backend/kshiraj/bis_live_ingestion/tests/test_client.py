import httpx

from kshiraj.bis_live_ingestion.adapters.bis_client import BISClient, BISClientConfig


def test_search_and_details_and_amendments():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
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
            }})
        if request.url.path.endswith("getAmendmentDetails"):
            return httpx.Response(200, json={"status": "SUCCESS", "data": []})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http:
        client = BISClient(BISClientConfig(max_retries=0), client=http)
        assert client.search_standards("IS 694:2010")[0]["standardEncId"] == "opaque-123"
        assert client.get_standard_details("opaque-123")["standardId"] == 123
        assert client.get_amendments(123) == []

    assert calls == [
        "/review-service/searchKnowStandards",
        "/review-service/getWebsiteStandardDetails",
        "/review-service/getAmendmentDetails",
    ]
