import io
import time

import openpyxl
from fastapi.testclient import TestClient

from ddq_agent.app import create_app
from ddq_agent.pipeline import run_review
from ddq_agent.store import Store

from .test_pipeline import FakeLLM, fake_connectors


def wait_for(client, review_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/reviews/{review_id}").json()
        if data["meta"]["status"] in ("done", "failed"):
            return data
        time.sleep(0.05)
    raise AssertionError("review did not finish")


def make_client(tmp_path, runner=None):
    def fake_runner(**kwargs):
        return run_review(llm=FakeLLM(), connectors_fn=fake_connectors, **kwargs)

    return TestClient(create_app(store=Store(tmp_path), runner=runner or fake_runner))


def test_address_review_end_to_end(tmp_path):
    client = make_client(tmp_path)
    assert "New review" in client.get("/").text

    meta = client.post("/api/reviews", data={"address": "1260 S Park Ave, Salt Lake City, UT 84105"}).json()
    data = wait_for(client, meta["id"])

    assert data["meta"]["status"] == "done"
    assert data["meta"]["summary"]["questions"] == 65
    assert "Looking up the property from its address" in data["meta"]["steps"]
    assert len(data["review"]["rows"]) == 65
    assert client.get(f"/reviews/{meta['id']}").status_code == 200

    xlsx = client.get(f"/api/reviews/{meta['id']}/report.xlsx")
    assert xlsx.status_code == 200
    assert "60%20Park%20ESG%20DDQ.xlsx" in xlsx.headers["content-disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(xlsx.content))
    assert wb.sheetnames[:2] == ["Summary", "ESG DDQ"]

    listed = client.get("/api/reviews").json()
    assert [m["id"] for m in listed] == [meta["id"]]


def test_om_upload_is_saved_and_reviewed(tmp_path):
    seen = {}

    def runner(address=None, documents=None, on_step=None):
        seen["docs"] = [(path.read_bytes(), label) for path, label in documents]
        seen["address"] = address
        return run_review(address=address, documents=documents, on_step=on_step, llm=FakeLLM(), connectors_fn=fake_connectors)

    client = make_client(tmp_path, runner)
    pdf = b"%PDF-1.4 sample"
    resp = client.post(
        "/api/reviews",
        data={"labels": ["Offering Memorandum", "Utility data"]},
        files=[("files", ("60 Park OM.pdf", pdf, "application/pdf")), ("files", ("bills.csv", b"month,kwh\n1,100\n", "text/csv"))],
    )
    assert resp.status_code == 201, resp.text
    data = wait_for(client, resp.json()["id"])
    assert data["meta"]["status"] == "done"
    assert seen == {
        "docs": [(pdf, "Offering Memorandum: 60 Park OM.pdf"), (b"month,kwh\n1,100\n", "Utility data: bills.csv")],
        "address": None,
    }
    assert [d["label"] for d in data["meta"]["documents"]] == ["Offering Memorandum", "Utility data"]
    assert "Reading 2 documents" in data["meta"]["steps"]


def test_rejects_empty_and_non_pdf_input(tmp_path):
    client = make_client(tmp_path)
    assert client.post("/api/reviews", data={"address": "  "}).status_code == 400
    bad = client.post("/api/reviews", files={"files": ("om.pdf", b"not a pdf", "application/pdf")})
    assert bad.status_code == 400
    exe = client.post("/api/reviews", files={"files": ("tool.exe", b"MZ", "application/octet-stream")})
    assert exe.status_code == 400
    assert client.get("/api/reviews").json() == []


def test_failed_review_reports_the_error(tmp_path):
    def broken(**kwargs):
        raise RuntimeError("API key missing")

    client = make_client(tmp_path, broken)
    meta = client.post("/api/reviews", data={"address": "1 Main St, Denver, CO"}).json()
    data = wait_for(client, meta["id"])
    assert data["meta"]["status"] == "failed"
    assert "API key missing" in data["meta"]["error"]
    assert client.get(f"/api/reviews/{meta['id']}/report.xlsx").status_code == 404


def test_unknown_review_is_404(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/api/reviews/../../etc").status_code == 404
    assert client.get("/api/reviews/20260101-000000-abcdef").status_code == 404


def test_settings_save_keys_without_echoing_secrets(tmp_path):
    client = make_client(tmp_path)
    state = client.post("/api/settings", json={"values": {"FIRST_STREET_API_KEY": "fs-secret", "ESPM_USERNAME": "surabhi"}}).json()
    fields = {f["key"]: f for f in state["fields"]}
    assert fields["FIRST_STREET_API_KEY"]["set"] and fields["FIRST_STREET_API_KEY"]["value"] is None
    assert fields["ESPM_USERNAME"]["value"] == "surabhi"
    assert "fs-secret" not in client.get("/api/settings").text
    assert "fs-secret" not in client.get("/settings").text

    from ddq_agent import settings
    from ddq_agent.connectors.climate import FirstStreet

    assert settings.get("FIRST_STREET_API_KEY") == "fs-secret"
    assert FirstStreet().missing_env() == []

    cleared = client.post("/api/settings", json={"values": {"FIRST_STREET_API_KEY": None}}).json()
    assert not {f["key"]: f for f in cleared["fields"]}["FIRST_STREET_API_KEY"]["set"]
    assert client.post("/api/settings", json={"values": {"NOT_A_SETTING": "x"}}).status_code == 400


def test_settings_dataset_upload_and_custom_sources(tmp_path):
    client = make_client(tmp_path)
    state = client.post(
        "/api/settings/file", data={"key": "CAMBIUM_CSV"}, files={"file": ("cambium.csv", b"state,year,scenario,lrmer_kg_per_mwh\n", "text/csv")}
    ).json()
    assert {f["key"]: f for f in state["fields"]}["CAMBIUM_CSV"]["value"].endswith("cambium.csv")
    assert client.post("/api/settings/file", data={"key": "BPD_API_KEY"}, files={"file": ("x.csv", b"", "text/csv")}).status_code == 400

    bad = client.post("/api/settings/sources", json={"name": "X", "url": "https://x.org/?q={secret}"})
    assert bad.status_code == 400
    state = client.post(
        "/api/settings/sources",
        json={"name": "County parcels", "url": "https://gis.example.gov/parcel?lat={lat}&lon={lon}",
              "header_name": "X-API-Key", "header_value": "parcel-secret"},
    ).json()
    [source] = state["custom_sources"]
    assert source["id"] == "county_parcels" and source["has_key"] and "header_value" not in source
    assert "parcel-secret" not in client.get("/api/settings").text
    assert client.delete("/api/settings/sources/county_parcels").json()["custom_sources"] == []


def test_password_protects_every_page_except_health_check(tmp_path, monkeypatch):
    monkeypatch.setenv("DDQ_PASSWORD", "s3cret")
    client = make_client(tmp_path)
    assert client.get("/healthz").status_code == 200
    for path in ("/", "/settings", "/api/reviews", "/api/settings"):
        r = client.get(path)
        assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"]
    assert client.get("/", auth=("ddq", "wrong")).status_code == 401
    assert client.get("/", auth=("ddq", "s3cret")).status_code == 200
    assert client.get("/api/settings", auth=("ddq", "s3cret")).status_code == 200


def test_restart_marks_unfinished_reviews_failed(tmp_path):
    store = Store(tmp_path)
    meta = store.create("1 Main St, Denver, CO", [])
    store.update(meta["id"], status="running")
    create_app(store=store, runner=lambda **kw: None)
    after = store.meta(meta["id"])
    assert after["status"] == "failed" and "restarted" in after["error"]
