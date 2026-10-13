from collections import Counter

import openpyxl

from ddq_agent.checklist import import_from_xlsx, load_template


def test_bundled_template_matches_team_checklist():
    items = load_template()
    assert len(items) == 65
    assert len({i.id for i in items}) == 65
    assert items[0].question.startswith("Environmental Performance Certificate")
    assert Counter(i.timing for i in items) == {"Post": 33, "Pre": 25, "": 6, "Pre/Post": 1}
    assert Counter(i.section for i in items)["LEASE"] == 4


def test_import_handles_continuation_blocks_and_stray_labels(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    header = ["ESG Consideration", "Response", "Existing Conditions", "Mitigation / Handling ", "Priority",
              "Type", "Risk", "Cost Estimate", None, "Pre/Post Site Visit (Hide for report)"]
    for row in [
        ["ENERGY"], header,
        ["Energy Star score?", "Y", "87", None, "LOW", "Energy", "LOW", None, None, "Pre "],
        [], header,  # continuation of ENERGY with no title
        ["Audit in last four years?", "N", None, None, "LOW", "Energy", "LOW", None, None, "Post"],
        ["Post"],  # stray label
        ["LEASE"], header,
        ["Green leases?", "Y", None, None, "LOW", "Tenants", "LOW", None, None, None],
    ]:
        ws.append(row)
    path = tmp_path / "c.xlsx"
    wb.save(path)

    items = import_from_xlsx(path)
    assert [(i.id, i.section, i.timing) for i in items] == [
        ("Q01", "ENERGY", "Pre"), ("Q02", "ENERGY", "Post"), ("Q03", "LEASE", ""),
    ]
