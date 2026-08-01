"""Per-domain data consent: the record, and the filter it drives.

The properties that matter here:
  - a user who has never reported shares everything (an absent record is "not
    yet reported", never a restriction — see the migration);
  - a report replaces the set wholesale, always includes `training`, and
    tolerates domains this server has never heard of;
  - a consent-scoped read (the coach) loses the unshared columns *entirely*,
    while the same read unscoped (the dashboard, the app) is untouched — the
    two paths share one endpoint, so testing only one proves nothing;
  - the column map covers every field the metrics payload can carry, so a new
    metric can't escape the filter by being forgotten.
"""

from datetime import date

import pytest

from app.data_consent import (
    ACTIVITY,
    BODY,
    DEFAULT_DOMAINS,
    DOMAIN_METRIC_FIELDS,
    NUTRITION,
    RECOVERY,
    TRAINING,
    UNGATED_METRIC_FIELDS,
    metric_fields_for,
    normalize,
)
from app.schemas.health_metrics import HealthMetricsRead

CONSENT = "/api/me/data-consent"
METRICS = "/api/health/metrics"
NUTRITION_BASE = "/api/nutrition"
COACH = {"X-Consent-Scope": "coach"}


# ── the map is the load-bearing part ────────────────────────────────────────


def test_domain_map_covers_every_metric_field():
    """A metric column added without a domain must fail here, not leak there.

    Every field of the read schema is either bookkeeping or governed by exactly
    one domain — the filter allow-lists by domain, so an unmapped field would
    silently vanish from consent-scoped payloads (or, under a drop-list, leak).
    """
    mapped = set().union(*DOMAIN_METRIC_FIELDS.values())
    assert mapped & UNGATED_METRIC_FIELDS == set()
    assert mapped | UNGATED_METRIC_FIELDS == set(HealthMetricsRead.model_fields)

    seen: set[str] = set()
    for fields in DOMAIN_METRIC_FIELDS.values():
        assert not (seen & fields), "a field belongs to exactly one domain"
        seen |= fields


def test_metric_fields_for_is_additive():
    assert metric_fields_for([]) == UNGATED_METRIC_FIELDS
    assert metric_fields_for([BODY]) == UNGATED_METRIC_FIELDS | DOMAIN_METRIC_FIELDS[BODY]
    assert metric_fields_for(DEFAULT_DOMAINS) == set(HealthMetricsRead.model_fields)


# ── normalisation ───────────────────────────────────────────────────────────


def test_training_is_always_shared():
    assert normalize([]) == [TRAINING]
    assert normalize([NUTRITION])[0] == TRAINING


def test_unknown_domains_are_kept_not_rejected():
    # A newer app may report a domain this server hasn't learned. Dropping it
    # would lose the athlete's choice the moment the server catches up.
    assert normalize(["nutrition", "mindfulness"]) == [TRAINING, NUTRITION, "mindfulness"]


def test_junk_is_bounded():
    assert normalize(["", "  ", "x" * 40]) == [TRAINING]
    assert normalize([f"d{i}" for i in range(50)]) == normalize([f"d{i}" for i in range(50)])[:20]
    assert len(normalize([f"d{i}" for i in range(50)])) == 20


def test_duplicates_collapse():
    assert normalize([BODY, BODY, TRAINING]) == [TRAINING, BODY]


# ── the record ──────────────────────────────────────────────────────────────


def test_default_is_permissive_and_unreported(client_a):
    body = client_a.get(CONSENT).json()
    assert body["domains"] == DEFAULT_DOMAINS
    # Never reported — distinguishable from "reported, and equals the default".
    assert body["updatedAt"] is None
    assert body["reportedAt"] is None


def test_put_replaces_wholesale(client_a):
    resp = client_a.put(CONSENT, json={"domains": [RECOVERY, ACTIVITY]})
    assert resp.status_code == 200
    assert resp.json()["domains"] == [TRAINING, RECOVERY, ACTIVITY]
    assert resp.json()["reportedAt"] is not None

    # Not a delta: the second report drops recovery/activity.
    assert client_a.put(CONSENT, json={"domains": [NUTRITION]}).json()["domains"] == [TRAINING, NUTRITION]
    assert client_a.get(CONSENT).json()["domains"] == [TRAINING, NUTRITION]


def test_repeat_report_stamps_reported_but_not_updated(client_a, client_admin):
    """The app reports on every launch — that must stay cheap and quiet."""
    first = client_a.put(CONSENT, json={"domains": [RECOVERY]}).json()
    again = client_a.put(CONSENT, json={"domains": [RECOVERY]}).json()

    assert again["updatedAt"] == first["updatedAt"]
    assert again["reportedAt"] >= first["reportedAt"]

    changes = [e for e in client_admin.get("/api/admin/events").json() if e["event"] == "data_consent_changed"]
    assert len(changes) == 1, "an unchanged re-report must not write an audit row"
    assert changes[0]["detail"]["domains"] == [TRAINING, RECOVERY]


def test_a_trailing_slash_still_works(client_a):
    """The SPA catch-all pre-empts FastAPI's slash redirect, so a client that
    appends one would get a 405 that reads exactly like "not implemented"."""
    assert client_a.put(f"{CONSENT}/", json={"domains": [BODY]}).status_code == 200
    assert client_a.get(f"{CONSENT}/").json()["domains"] == [TRAINING, BODY]


def test_consent_is_per_user(client_a, client_b):
    client_a.put(CONSENT, json={"domains": []})
    assert client_a.get(CONSENT).json()["domains"] == [TRAINING]
    assert client_b.get(CONSENT).json()["domains"] == DEFAULT_DOMAINS


# ── the filter ──────────────────────────────────────────────────────────────


@pytest.fixture()
def metrics_day(client_a):
    client_a.post(
        METRICS,
        json={
            "metrics": [
                {
                    "date": "2026-07-20",
                    "sleep_duration": 7.5,
                    "resting_heart_rate": 48,
                    "weight": 74.2,
                    "steps": 9000,
                    "active_energy_burned": 620,
                }
            ]
        },
    )
    return "2026-07-20"


def test_unscoped_read_is_untouched(client_a, metrics_day):
    """The athlete's own dashboard must not be filtered by the coach's setting."""
    client_a.put(CONSENT, json={"domains": []})
    row = client_a.get(METRICS, params={"start_date": metrics_day}).json()[0]
    assert set(row) == set(HealthMetricsRead.model_fields)
    assert row["weight"] == 74.2


def test_scoped_read_drops_unshared_columns(client_a, metrics_day):
    client_a.put(CONSENT, json={"domains": [ACTIVITY]})
    row = client_a.get(METRICS, params={"start_date": metrics_day}, headers=COACH).json()[0]

    assert row["steps"] == 9000
    assert row["active_energy_burned"] == 620
    # Absent, not null: null means "not tracked" everywhere else in this
    # payload, and the coach would report a gap the athlete does not have.
    for field in ("weight", "sleep_duration", "resting_heart_rate", "vo2_max"):
        assert field not in row
    assert row["date"] == metrics_day


def test_scoped_read_of_a_fully_unshared_table_is_refused(client_a, metrics_day):
    client_a.put(CONSENT, json={"domains": [NUTRITION]})
    resp = client_a.get(METRICS, params={"start_date": metrics_day}, headers=COACH)
    assert resp.status_code == 403
    # The wording must not send the coach off telling the athlete to track more.
    assert "not share" in resp.json()["detail"]
    assert "sharing setting, not missing data" in resp.json()["detail"]


def test_scoped_nutrition_is_refused_when_unshared(client_a):
    client_a.put(CONSENT, json={"domains": [RECOVERY]})
    for path in (NUTRITION_BASE, f"{NUTRITION_BASE}/summary"):
        resp = client_a.get(path, params={"start_date": "2026-07-01"}, headers=COACH)
        assert resp.status_code == 403, path
    # …and stays readable for the athlete's own dashboard.
    assert client_a.get(NUTRITION_BASE, params={"start_date": "2026-07-01"}).status_code == 200


def test_summary_drops_body_and_expenditure_blocks(client_a, metrics_day):
    """The summary is named for nutrition but carries weight and energy too."""
    client_a.post(NUTRITION_BASE, json={"days": [{"date": metrics_day, "energy_kcal": 2400, "protein_g": 130}]})
    params = {"start_date": "2026-07-20", "end_date": "2026-07-26", "period": "week"}

    client_a.put(CONSENT, json={"domains": [NUTRITION]})
    period = client_a.get(f"{NUTRITION_BASE}/summary", params=params, headers=COACH).json()["periods"][0]
    assert period["nutrition"]["energy_kcal"] is not None
    assert "body" not in period
    assert "protein_g_per_kg" not in period, "weight data wearing a nutrition name"
    assert "expenditure" not in period
    assert "training" in period

    client_a.put(CONSENT, json={"domains": [NUTRITION, BODY, ACTIVITY]})
    period = client_a.get(f"{NUTRITION_BASE}/summary", params=params, headers=COACH).json()["periods"][0]
    assert period["body"]["weight_avg"] == 74.2
    assert period["expenditure"]["active_kcal_avg"] is not None


def test_unknown_scope_value_still_filters(client_a, metrics_day):
    """An unrecognised scope must not be the thing that disables filtering."""
    client_a.put(CONSENT, json={"domains": [ACTIVITY]})
    row = client_a.get(METRICS, params={"start_date": metrics_day}, headers={"X-Consent-Scope": "future"}).json()[0]
    assert "weight" not in row


def test_writes_are_never_filtered(client_a):
    """Consent shapes what the coach reads; the app keeps syncing regardless.

    (The app already omits unconsented columns from its uploads — but a server
    that rejected them would strand a client mid-migration.)
    """
    client_a.put(CONSENT, json={"domains": []})
    resp = client_a.post(
        METRICS, json={"metrics": [{"date": "2026-07-21", "weight": 74.0}]}, headers=COACH
    )
    assert resp.status_code == 200
    assert resp.json()["upserted"] == 1


def test_new_user_matches_the_declared_default(session_factory):
    """The model's DDL default is a literal (it can't import the module that
    declares DEFAULT_DOMAINS without a cycle) — so pin them together here."""
    from app.models.user import User

    with session_factory() as db:
        user = User(username="fresh", display_name="fresh", role="user")
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.data_consent == DEFAULT_DOMAINS
        assert user.data_consent_reported_at is None
