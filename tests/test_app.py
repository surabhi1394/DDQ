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

    def runner(om_path=None, address=None, on_step=None):
        seen["om"] = om_path.read_bytes()
        seen["address"] = address
        return run_review(om_path=om_path, address=address, on_step=on_step, llm=FakeLLM(), connectors_fn=fake_connectors)

    client = make_client(tmp_path, runner)
    pdf = b"%PDF-1.4 sample"
    meta = client.post("/api/reviews", files={"om": ("60 Park OM.pdf", pdf, "application/pdf")}).json()
    data = wait_for(client, meta["id"])
    assert data["meta"]["status"] == "done"
    assert seen == {"om": pdf, "address": None}
    assert data["meta"]["om_name"] == "60 Park OM.pdf"
    assert "Indexing the Offering Memorandum" in data["meta"]["steps"]


def test_rejects_empty_and_non_pdf_input(tmp_path):
    client = make_client(tmp_path)
    assert client.post("/api/reviews", data={"address": "  "}).status_code == 400
    bad = client.post("/api/reviews", files={"om": ("om.pdf", b"not a pdf", "application/pdf")})
    assert bad.status_code == 400
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
