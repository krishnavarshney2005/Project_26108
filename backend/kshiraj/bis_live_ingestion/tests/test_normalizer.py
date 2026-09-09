from kshiraj.bis_live_ingestion.normalizer import normalize_designation, normalize_standard


def test_normalize_designation():
    assert normalize_designation(" IS 10322 (Part 5 / Sec 3) : 2012 ") == "IS 10322 (Part 5/Sec 3):2012"


def test_numeric_status_is_not_inferred_as_active():
    standard, evidence = normalize_standard({
        "standardNumber": "IS 694:2010",
        "standardName": "PVC insulated cables",
        "publishedOn": "2010-01-01",
        "isStatus": 1,
        "withdrawStatus": 0,
    })
    assert standard.status.value == "unknown"
    assert evidence[0].authority == "BIS"
