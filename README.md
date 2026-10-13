# DDQ agent

An ESG due diligence questionnaire (DDQ) tool for over-the-desk reviews. Enter a property address,
upload its Offering Memorandum (OM), or both. The agent runs the full analysis, shows the results on a
dashboard, and gives you an Excel download of the completed ESG DDQ checklist and all the data it found.
You can add more documents (PCA, Phase I ESA, energy audits, utility data, leases) and more API keys
or custom data sources, and every review also searches free public tools such as FEMA, USGS and First Street.

## How it works

```
Address and/or documents received (OM, PCA, Phase I ESA, audits, utility data, leases)
  └─ RSRA agent
       ├─ index the documents, or look the property up from its address with web search
       ├─ connectors: geocode · FEMA flood · FEMA National Risk Index · USGS seismic · USGS elevation ·
       │   First Street · physrisk · ENERGY STAR · CRREM · Cambium · BPD · Fines & Regs · Audette · custom sources
       ├─ research gaps with web search: assessor records, registries, local rules, First Street Risk Factor,
       │   FEMA, USFS wildfire, NOAA sea level rise, USGS, EPA radon and Envirofacts, transit, tenants
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
cp .env.example .env   # optional: keys can also be entered on the Settings page
set -a && source .env && set +a
```

Check which data sources are live:

```bash
ddq connectors
```

## Use the web tool

```bash
ddq serve            # then open http://127.0.0.1:8000
```

- **New review:** type an address, drop in one or more documents, or both, and press Start review.
  Each file gets a type (OM, PCA, Phase I ESA, energy audit, utility data, lease and so on), guessed
  from its name. PDF, images, Excel, CSV and text files are accepted, up to 22 MB in total.
- **Settings:** add API keys (Anthropic, ENERGY STAR, First Street, BPD, Audette), upload the CRREM and
  Cambium CSVs, and add **custom sources**: any API that returns property or location data. Its URL can
  use `{lat}` `{lon}` `{address}` `{street}` `{city}` `{state}` `{zip}`, with an optional key header, and
  its response goes to the agents on every review. Saved keys are never shown again.
- **Progress:** the review page shows each step as it runs (a full review takes several minutes).
- **Dashboard:** headline counts, risk profile, key findings, property facts, recommended actions and
  costs, the status of every data source, and the full checklist with search and filters.
- **Excel:** Summary, ESG DDQ (the team's checklist layout), Data sources and research notes,
  Connector data (every value each source returned) and Property.

Reviews are saved under `ddq_data/` (set `DDQ_DATA_DIR` to change it), one folder per review.
To share it from your own server, set `DDQ_PASSWORD` and run `ddq serve --host 0.0.0.0`. Every page then
asks for that password. Without it, anyone who can open the tool can start reviews and change Settings.
Saved keys live in `ddq_data/settings.json` (file mode 600); a saved value overrides the environment.

## Put it online for the team (Render)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/surabhi1394/DDQ)

1. Click the button (or in Render choose **New > Blueprint** and pick this repo). Render reads `render.yaml`.
2. When asked, enter `DDQ_PASSWORD` (the team's sign-in password) and `ANTHROPIC_API_KEY`.
3. Render builds it and gives you a link like `https://ddq-xxxx.onrender.com`. Sign in with user `ddq`
   (or set `DDQ_USERNAME`) and the password. Other keys can then be added on the Settings page.

The Blueprint uses Render's **free** plan. It sleeps after 15 minutes without visitors (the first
visit after that takes about a minute to wake it, so keep a review's page open until it finishes), and it has no disk, so reviews are cleared when it
sleeps or redeploys: download the Excel when a review finishes. Keys entered in Render's environment
settings are kept; keys typed on the Settings page are not. To keep everything, switch to the Starter
plan and uncomment the disk lines in `render.yaml`. Claude API usage is billed by Anthropic either way.

## Run a review from the command line

```bash
ddq review --address "1260 S Park Ave, Salt Lake City, UT 84105"
ddq review samples/60_Park_Ave_OM.pdf -o samples/60_Park.ddq.xlsx --json samples/60_Park.ddq.json
ddq review samples/60_Park_Ave_OM.pdf --doc "Phase I ESA=samples/phase1.pdf" --doc "Utility data=samples/bills.xlsx"
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
| fema_nri | FEMA National Risk Index ratings for 18 hazards in the census tract | nothing (override with `NRI_URL`) |
| usgs_seismic | USGS ASCE 7-22 seismic design values and design category | nothing |
| usgs_elevation | USGS ground elevation | nothing |
| first_street | Property-level flood, fire, heat, wind and air risk | `FIRST_STREET_API_KEY` (endpoint via `FIRST_STREET_URL`) |
| physrisk | Flood, heat and wind indicators under a climate scenario | `PHYSRISK_API_URL` (your physrisk-api deployment) |
| energy_star | Score, weather-normalized EUI, GHG from Portfolio Manager | `ESPM_USERNAME`, `ESPM_PASSWORD`, property id |
| crrem | Energy and carbon stranding years | `CRREM_PATHWAYS_CSV` (your CRREM export) |
| cambium | Projected grid emission factors for the state | `CAMBIUM_CSV` (NREL download) |
| bpd | Peer EUI benchmarks | `BPD_API_KEY` (client to implement) |
| fines_regs | Local benchmarking / performance standards and penalties | nothing (`ddq_agent/data/regulations.yaml`) |
| audette | Modelled retrofit measures and capex | `AUDETTE_API_KEY` (client to implement) |
| custom:… | Whatever the API you added in Settings returns | the key you add with it |
| web search | Anything public, including First Street's free Risk Factor pages | nothing (Claude server tool) |

Credentials can come from the environment or the Settings page. A connector without credentials reports `not_configured` and the agents are told not to use it,
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
