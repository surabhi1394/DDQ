# DDQ agent

An ESG due diligence questionnaire (DDQ) agent for over-the-desk reviews. Give it an Offering
Memorandum (OM) PDF and it returns the team's ESG DDQ checklist, filled in and source-cited, in the
same spreadsheet layout the team already uses.

## How it works

```
OM received
  └─ RSRA agent
       ├─ index the OM (property facts, systems, certifications, disclosures)
       ├─ connectors: geocode · FEMA flood · physrisk · ENERGY STAR · CRREM · Cambium · BPD · Fines & Regs · Audette
       ├─ research gaps with web search (local rules, transit, hazards, tenants, registries)
       └─ assemble findings: one answer per checklist question
  └─ Retrofit Specialist: Mitigation, Cost Estimate, Priority, Risk (uses the team cost library)
  └─ Verifier: checks every answer against its sources; failures go back to the RSRA agent
     (up to 2 rounds), anything still unsupported is flagged NEEDS REVIEW
  └─ Report: the checklist .xlsx, plus "Data sources" and "Property" sheets
```

Questions marked **Post** (site visit) are answered from the documents where possible and marked
"Confirm on site visit" when the documents don't settle them.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # add ANTHROPIC_API_KEY, plus any connector credentials you have
set -a && source .env && set +a
```

Check which data sources are live:

```bash
ddq connectors
```

## Run a review

```bash
ddq review samples/60_Park_Ave_OM.pdf -o samples/60_Park.ddq.xlsx --json samples/60_Park.ddq.json
```

Compare it with a checklist the team completed by hand for the same property:

```bash
ddq eval samples/60_Park.ddq.xlsx "samples/60 Park ESG DDQ CHECKLIST.xlsx"
```

`samples/` is git-ignored so deal documents stay off GitHub.

## Connectors

| Connector | What it adds | Needs |
|---|---|---|
| geocode | Latitude/longitude from the OM address (US Census) | nothing |
| fema_flood | FEMA flood zone and Special Flood Hazard Area status | nothing |
| physrisk | Flood, heat and wind indicators under a climate scenario | `PHYSRISK_API_URL` (your physrisk-api deployment) |
| energy_star | Score, weather-normalized EUI, GHG from Portfolio Manager | `ESPM_USERNAME`, `ESPM_PASSWORD`, property id |
| crrem | Energy and carbon stranding years | `CRREM_PATHWAYS_CSV` (your CRREM export) |
| cambium | Projected grid emission factors for the state | `CAMBIUM_CSV` (NREL download) |
| bpd | Peer EUI benchmarks | `BPD_API_KEY` (client to implement) |
| fines_regs | Local benchmarking / performance standards and penalties | nothing (`ddq_agent/data/regulations.yaml`) |
| audette | Modelled retrofit measures and capex | `AUDETTE_API_KEY` (client to implement) |
| web search | Anything public the checklist needs | nothing (Claude server tool) |

A connector without credentials reports `not_configured` and the agents are told not to use it,
so a review always runs end to end.

**Plugging in Audette later:** set `AUDETTE_API_KEY` and fill in `Audette.fetch()` in
`ddq_agent/connectors/plugins.py`, returning measures in `data["measures"]`. The Retrofit Specialist
already prefers Audette's measures and costs when they are present.

## Customizing

- **Checklist:** `ddq_agent/data/checklist_template.json`, generated from the team spreadsheet.
  Rebuild it after editing the spreadsheet:
  `python -m ddq_agent.checklist "path/to/checklist.xlsx" ddq_agent/data/checklist_template.json`
- **Cost library:** `ddq_agent/data/cost_library.yaml`. The Retrofit Specialist quotes these lines verbatim.
- **Local rules:** `ddq_agent/data/regulations.yaml`. Every entry is confirmed with web search during a review.
- **House style and prompts:** `ddq_agent/agents/prompts.py`.
- **Model:** `DDQ_MODEL` (default `claude-opus-5-5`) and `DDQ_EFFORT` (default `high`).

## Tests

```bash
pytest
```

The tests run the whole workflow with a fake model and mocked HTTP, so they need no API key.
