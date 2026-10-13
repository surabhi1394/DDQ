import openpyxl
import pytest

from ddq_agent.llm import document_block, document_blocks


def test_document_types_become_readable_blocks(tmp_path):
    pdf = tmp_path / "om.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    csv = tmp_path / "bills.csv"
    csv.write_text("month,kwh\nJan,1000\n")
    xlsx = tmp_path / "audit.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Measures"
    wb.active.append(["Measure", "Savings"])
    wb.active.append(["LED retrofit", 12000])
    wb.save(xlsx)
    png = tmp_path / "photo.png"
    png.write_bytes(b"\x89PNG")

    assert document_block(pdf)["source"]["media_type"] == "application/pdf"
    assert document_block(csv)["source"] == {"type": "text", "media_type": "text/plain", "data": "month,kwh\nJan,1000\n"}
    assert "LED retrofit,12000" in document_block(xlsx)["source"]["data"]
    assert document_block(png)["type"] == "image"
    with pytest.raises(ValueError):
        document_block(tmp_path / "notes.docx")

    blocks = document_blocks([(pdf, "Offering Memorandum: om.pdf"), (csv, "Utility data: bills.csv")])
    assert [b["type"] for b in blocks] == ["text", "document", "text", "document"]
    assert blocks[0]["text"] == "Document: Offering Memorandum: om.pdf"
    # One cache breakpoint at the end of the documents, however many there are (the API allows four).
    assert [i for i, b in enumerate(blocks) if "cache_control" in b] == [3]
