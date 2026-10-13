import httpx

from ddq_agent.connectors import ConnectorContext, run_connectors
from ddq_agent.connectors.base import Connector
from ddq_agent.connectors.energy_star import parse_metrics
from ddq_agent.connectors.location import FemaFlood, Geocode
from ddq_agent.connectors.pathways import Cambium, Crrem, stranding_year
from ddq_agent.connectors.plugins import Audette
from ddq_agent.connectors.regs import FinesRegs, load_rules, matching_rules
from ddq_agent.models import ConnectorResult, ConnectorStatus, PropertyProfile

SLC = PropertyProfile(
    street_address="1260 S Park Ave", city="Salt Lake City", state="UT", property_type="Office",
    gross_floor_area_sqft=143_806, site_eui_kbtu_sqft=47.7,
)


def test_regs_match_city_and_size():
    hits = matching_rules("Salt Lake City", "UT", 143_806, load_rules())
    assert [h["name"] for h in hits] == ["Salt Lake City Elevate Buildings"]
    assert hits[0]["covered"]
    assert not matching_rules("Salt Lake City", "UT", 10_000, load_rules())[0]["covered"]
    # State-wide rules apply to every city in the state.
    assert "Colorado Building Performance Standard" in [h["name"] for h in matching_rules("Aurora", "CO", 80_000, load_rules())]


def test_fines_regs_no_rule_says_to_search():
    r = FinesRegs().run(ConnectorContext(profile=PropertyProfile(city="Boise", state="ID")))
    assert r.status == ConnectorStatus.NO_DATA and "web search" in r.summary


def test_stranding_year():
    path = {2025: 150.0, 2030: 120.0, 2035: 90.0}
    assert stranding_year(100.0, path) == 2035
    assert stranding_year(160.0, path) == 2025
    assert stranding_year(50.0, path) is None


def test_crrem_uses_energy_star_eui_over_om(tmp_path, monkeypatch):
    csv = tmp_path / "crrem.csv"
    csv.write_text(
        "country,property_type,year,energy_kwh_m2,carbon_kgco2e_m2\n"
        "US,office,2025,200,40\nUS,office,2030,160,25\nUS,office,2035,120,12\n"
    )
    monkeypatch.setenv("CRREM_PATHWAYS_CSV", str(csv))
    ctx = ConnectorContext(profile=SLC)
    ctx.results["energy_star"] = ConnectorResult(
        connector="energy_star", status=ConnectorStatus.OK,
        data={"siteIntensityWN": "45", "totalLocationBasedGHGEmissions": "400"},
    )
    r = Crrem().run(ctx)
    assert r.status == ConnectorStatus.OK
    assert r.data["eui_source"] == "ENERGY STAR Portfolio Manager"
    assert r.data["site_eui_kwh_m2"] == 142.0  # 45 kBtu/sf
    assert r.data["energy_stranding_year"] == 2035
    assert r.data["carbon_stranding_year"] == 2030  # ~29.9 kg/m2 exceeds the 2030 limit of 25


def test_cambium_filters_state(tmp_path, monkeypatch):
    csv = tmp_path / "cambium.csv"
    csv.write_text("state,year,scenario,lrmer_kg_per_mwh\nUT,2030,mid,610\nUT,2040,mid,420\nCO,2030,mid,500\n")
    monkeypatch.setenv("CAMBIUM_CSV", str(csv))
    r = Cambium().run(ConnectorContext(profile=SLC))
    assert r.data["lrmer_kg_per_mwh"] == {"mid:2030": 610.0, "mid:2040": 420.0}


def test_parse_espm_metrics():
    xml = (
        '<propertyMetrics propertyId="30802518" month="12" year="2025">'
        '<metric name="score" uom="" dataType="numeric"><value>87</value></metric>'
        '<metric name="siteIntensityWN" uom="kBtu/ft2" dataType="numeric"><value>47.7</value></metric>'
        '<metric name="sourceIntensityWN" dataType="numeric"><value/></metric>'
        "</propertyMetrics>"
    )
    assert parse_metrics(xml) == {"score": "87", "siteIntensityWN": "47.7"}


def test_unconfigured_and_failing_connectors_do_not_raise(monkeypatch):
    monkeypatch.delenv("AUDETTE_API_KEY", raising=False)
    assert Audette().run(ConnectorContext(profile=SLC)).status == ConnectorStatus.NOT_CONFIGURED

    class Broken(Connector):
        name = "broken"

        def fetch(self, ctx):
            raise ValueError("boom")

    results = run_connectors(SLC, [Broken(), FinesRegs()])
    assert [r.status for r in results] == [ConnectorStatus.ERROR, ConnectorStatus.OK]
    assert "boom" in results[0].summary


def test_geocode_then_flood_zone():
    def handler(request: httpx.Request):
        if "census" in request.url.host:
            return httpx.Response(200, json={"result": {"addressMatches": [
                {"matchedAddress": "1260 S PARK AVE, SALT LAKE CITY, UT", "coordinates": {"x": -111.88, "y": 40.74}}
            ]}})
        assert request.url.params["geometry"] == "-111.88,40.74"
        return httpx.Response(200, json={"features": [{"attributes": {"FLD_ZONE": "X", "ZONE_SUBTY": "AREA OF MINIMAL FLOOD HAZARD", "SFHA_TF": "F"}}]})

    ctx = ConnectorContext(profile=SLC, http=httpx.Client(transport=httpx.MockTransport(handler)))
    results = run_connectors(SLC, [Geocode(), FemaFlood()], ctx)
    assert results[0].status == ConnectorStatus.OK and ctx.latitude == 40.74
    assert results[1].data == {"zone": "X", "subtype": "AREA OF MINIMAL FLOOD HAZARD", "sfha": False}
    assert "outside the Special Flood Hazard Area" in results[1].summary


def test_new_connectors_need_coordinates():
    from ddq_agent.connectors.climate import FemaRiskIndex, UsgsElevation, UsgsSeismic

    for c in (FemaRiskIndex(), UsgsSeismic(), UsgsElevation()):
        assert c.run(ConnectorContext(profile=SLC)).status == ConnectorStatus.NO_DATA


def test_climate_connectors_parse_responses():
    from ddq_agent.connectors.climate import FemaRiskIndex, UsgsElevation, UsgsSeismic

    def handler(request: httpx.Request):
        host = request.url.host
        if host == "services.arcgis.com":
            return httpx.Response(200, json={"features": [{"attributes": {
                "TRACTFIPS": "49035114000", "RISK_RATNG": "Relatively Moderate", "SOVI_RATNG": "Relatively Low",
                "ERQK_RISKR": "Very High", "WFIR_RISKR": "Relatively Moderate", "HWAV_RISKR": "Relatively High",
                "CFLD_RISKR": "Not Applicable",
            }}]})
        if host == "earthquake.usgs.gov":
            assert request.url.params["latitude"] == "40.74"
            return httpx.Response(200, json={"response": {"data": {"sds": 1.02, "sd1": 0.41, "sdc": "D", "other": 1}}})
        if host == "epqs.nationalmap.gov":
            return httpx.Response(200, json={"value": "4271.36"})
        raise AssertionError(host)

    ctx = ConnectorContext(profile=SLC, latitude=40.74, longitude=-111.88, http=httpx.Client(transport=httpx.MockTransport(handler)))
    nri = FemaRiskIndex().run(ctx)
    assert nri.status == ConnectorStatus.OK
    assert nri.data["hazards"] == {"Earthquake": "Very High", "Heat wave": "Relatively High", "Wildfire": "Relatively Moderate"}
    assert "Earthquake (Very High)" in nri.summary and "Heat wave (Relatively High)" in nri.summary
    seismic = UsgsSeismic().run(ctx)
    assert seismic.data == {"sds": 1.02, "sd1": 0.41, "sdc": "D"}
    assert UsgsElevation().run(ctx).data == {"elevation_ft": 4271.4}


def test_custom_source_fills_url_and_sends_key():
    from ddq_agent.connectors.climate import CustomSource

    def handler(request: httpx.Request):
        assert str(request.url) == "https://gis.example.gov/parcel?lat=40.740000&lon=-111.880000&city=Salt%20Lake%20City"
        assert request.headers["X-API-Key"] == "k"
        return httpx.Response(200, json={"parcel": "16-20-276-065", "year_built": 2020})

    source = {"id": "parcels", "name": "County parcels", "url": "https://gis.example.gov/parcel?lat={lat}&lon={lon}&city={city}",
              "header_name": "X-API-Key", "header_value": "k"}
    ctx = ConnectorContext(profile=SLC, latitude=40.74, longitude=-111.88, http=httpx.Client(transport=httpx.MockTransport(handler)))
    r = CustomSource(source).run(ctx)
    assert r.connector == "custom:parcels" and r.status == ConnectorStatus.OK
    assert '"year_built": 2020' in r.data["response"]
