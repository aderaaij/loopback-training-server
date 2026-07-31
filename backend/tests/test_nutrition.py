"""Route tests for /api/nutrition/* plus the pure period summariser.

The properties that matter here:
  - a partial-day sync must never overwrite a stored complete day with less
    data, and must stay out of averages until it completes (the sleep/steps
    corruption class, applied to a sum-by-day quantity);
  - omitted nutrients must not erase stored ones;
  - the summary must align intake, weight and load on the same period without
    the caller doing date arithmetic;
  - nutrition is per-user data, like everything else.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.workout import Workout
from app.nutrition_summary import (
    EnergyDay,
    NutritionDay,
    WeightPoint,
    WorkoutLoad,
    bucket_end,
    bucket_start,
    weight_trend,
    summarize,
)

BASE = "/api/nutrition"
METRICS = "/api/health/metrics"


def day_payload(day: str, **fields) -> dict:
    return {"date": day, **fields}


# ── upsert semantics ────────────────────────────────────────────────────────


def test_upsert_and_read_back(client_a):
    resp = client_a.post(
        BASE,
        json={
            "days": [
                day_payload(
                    "2026-07-01",
                    energy_kcal=2450.5,
                    carbs_g=310.2,
                    protein_g=140.0,
                    fat_g=80.4,
                    micros={"iron_mg": 14.2},
                    entry_count=5,
                    sources=["MyFitnessPal"],
                )
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"upserted": 1}

    rows = client_a.get(f"{BASE}?start_date=2026-07-01").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["date"] == "2026-07-01"
    assert row["energy_kcal"] == 2450.5
    assert row["protein_g"] == 140.0
    assert row["micros"] == {"iron_mg": 14.2}
    assert row["sources"] == ["MyFitnessPal"]
    assert row["entry_count"] == 5
    assert row["partial"] is False


def test_omitted_nutrients_do_not_erase_stored_values(client_a):
    """An older app build that only knows energy/macros must not blank the
    micronutrients a newer one stored."""
    client_a.post(
        BASE,
        json={"days": [day_payload("2026-07-02", energy_kcal=2000, protein_g=120, fiber_g=30)]},
    )
    client_a.post(BASE, json={"days": [day_payload("2026-07-02", energy_kcal=2100)]})

    row = client_a.get(f"{BASE}?start_date=2026-07-02").json()[0]
    assert row["energy_kcal"] == 2100  # updated
    assert row["protein_g"] == 120  # preserved
    assert row["fiber_g"] == 30  # preserved


def test_partial_day_is_flagged_then_completed(client_a):
    client_a.post(
        BASE, json={"days": [day_payload("2026-07-03", energy_kcal=900, partial=True)]}
    )
    row = client_a.get(f"{BASE}?start_date=2026-07-03").json()[0]
    assert row["partial"] is True
    assert row["energy_kcal"] == 900

    # A later sync of the completed day clears the flag.
    client_a.post(
        BASE, json={"days": [day_payload("2026-07-03", energy_kcal=2400, partial=False)]}
    )
    row = client_a.get(f"{BASE}?start_date=2026-07-03").json()[0]
    assert row["partial"] is False
    assert row["energy_kcal"] == 2400


def test_clear_retracts_a_stored_field(client_a):
    """The mirror of the rule above: omission means "no opinion", so a client
    that stops reporting a field needs `clear` to retract it. Without this,
    a value the client no longer stands behind lives forever."""
    client_a.post(
        BASE,
        json={"days": [day_payload("2026-07-02", energy_kcal=2000, potassium_mg=206,
                                   micros={"iron_mg": 1.6, "calcium_mg": 38})]},
    )
    # A later sync that simply omits them must NOT clear them...
    client_a.post(BASE, json={"days": [day_payload("2026-07-02", energy_kcal=2100)]})
    row = client_a.get(f"{BASE}?start_date=2026-07-02").json()[0]
    assert row["micros"] == {"iron_mg": 1.6, "calcium_mg": 38}
    assert row["potassium_mg"] == 206

    # ...but naming them in `clear` must.
    resp = client_a.post(
        BASE, json={"days": [{"date": "2026-07-02", "clear": ["micros", "potassium_mg"]}]}
    )
    assert resp.status_code == 200
    row = client_a.get(f"{BASE}?start_date=2026-07-02").json()[0]
    assert row["micros"] is None
    assert row["potassium_mg"] is None
    assert row["energy_kcal"] == 2100  # untouched


def test_clear_on_a_new_day_is_harmless(client_a):
    client_a.post(BASE, json={"days": [{"date": "2026-07-09", "energy_kcal": 1800, "clear": ["micros"]}]})
    row = client_a.get(f"{BASE}?start_date=2026-07-09").json()[0]
    assert row["energy_kcal"] == 1800
    assert row["micros"] is None


def test_clear_rejects_unknown_and_non_clearable_fields(client_a):
    for field in ("nonsense", "partial", "date"):
        resp = client_a.post(BASE, json={"days": [{"date": "2026-07-02", "clear": [field]}]})
        assert resp.status_code == 422, field


def test_clear_conflicting_with_a_value_is_rejected(client_a):
    """Guessing which one wins would silently drop data."""
    resp = client_a.post(
        BASE, json={"days": [{"date": "2026-07-02", "potassium_mg": 200, "clear": ["potassium_mg"]}]}
    )
    assert resp.status_code == 422


def test_delete_removes_a_day(client_a):
    client_a.post(
        BASE,
        json={"days": [day_payload("2026-07-10", energy_kcal=2000),
                       day_payload("2026-07-11", energy_kcal=2100)]},
    )
    resp = client_a.delete(f"{BASE}/2026-07-10")
    assert resp.status_code == 200
    assert resp.json() == {"date": "2026-07-10", "deleted": 1}
    assert [r["date"] for r in client_a.get(f"{BASE}?start_date=2026-07-01").json()] == ["2026-07-11"]


def test_delete_missing_day_404s(client_a):
    assert client_a.delete(f"{BASE}/2026-07-10").status_code == 404


def test_delete_cannot_reach_another_users_day(client_a, client_b):
    client_a.post(BASE, json={"days": [day_payload("2026-07-12", energy_kcal=2000)]})
    assert client_b.delete(f"{BASE}/2026-07-12").status_code == 404
    assert len(client_a.get(f"{BASE}?start_date=2026-07-12").json()) == 1


def test_summary_path_not_shadowed_by_the_delete_route(client_a):
    """`/summary` and `/{day}` share a prefix — the date-typed path must not
    swallow the summary route (different methods, but worth pinning)."""
    assert client_a.get(f"{BASE}/summary?start_date=2026-07-01").status_code == 200
    assert client_a.delete(f"{BASE}/summary").status_code == 422  # not a date


def test_camel_case_aliases_accepted(client_a):
    """The wire accepts both casings, as health metrics does."""
    resp = client_a.post(
        BASE,
        json={"days": [{"date": "2026-07-04", "energyKcal": 2200, "saturatedFatG": 21.5, "entryCount": 4}]},
    )
    assert resp.status_code == 200
    row = client_a.get(f"{BASE}?start_date=2026-07-04").json()[0]
    assert row["energy_kcal"] == 2200
    assert row["saturated_fat_g"] == 21.5
    assert row["entry_count"] == 4


def test_range_and_limit(client_a):
    client_a.post(
        BASE,
        json={
            "days": [
                day_payload("2026-07-05", energy_kcal=2000),
                day_payload("2026-07-06", energy_kcal=2100),
                day_payload("2026-07-07", energy_kcal=2200),
            ]
        },
    )
    rows = client_a.get(f"{BASE}?start_date=2026-07-06").json()
    assert [r["date"] for r in rows] == ["2026-07-07", "2026-07-06"]  # newest first

    rows = client_a.get(f"{BASE}?start_date=2026-07-05&end_date=2026-07-06").json()
    assert [r["date"] for r in rows] == ["2026-07-06", "2026-07-05"]

    rows = client_a.get(f"{BASE}?start_date=2026-07-05&limit=1").json()
    assert [r["date"] for r in rows] == ["2026-07-07"]


def test_nutrition_is_scoped_per_user(client_a, client_b):
    client_a.post(BASE, json={"days": [day_payload("2026-07-08", energy_kcal=2000)]})
    assert client_b.get(f"{BASE}?start_date=2026-07-01").json() == []


# ── summary ────────────────────────────────────────────────────────────────


def test_summary_aligns_intake_weight_and_load(client_a, session_factory, user_a):
    """One call answers "what did I eat, what did the scale do, what did I run"
    for the same week."""
    # Mon 2026-06-29 → Sun 2026-07-05.
    client_a.post(
        BASE,
        json={
            "days": [
                day_payload("2026-06-29", energy_kcal=2000, protein_g=100, carbs_g=250),
                day_payload("2026-06-30", energy_kcal=2400, protein_g=140, carbs_g=300),
            ]
        },
    )
    client_a.post(
        METRICS,
        json={
            "metrics": [
                {"date": "2026-06-29", "weight": 70.0},
                {"date": "2026-07-01", "weight": 69.5},
            ]
        },
    )
    with session_factory() as db:
        db.add(
            Workout(
                id="11111111-1111-1111-1111-111111111111",
                user_id=user_a[0],
                activity_type="running",
                start_date=datetime(2026, 6, 30, 8, 0, tzinfo=timezone.utc),
                end_date=datetime(2026, 6, 30, 9, 0, tzinfo=timezone.utc),
                duration=3600,
                total_distance=12000,
                total_energy_burned=800,
                source="test",
                data={},
            )
        )
        db.commit()

    body = client_a.get(f"{BASE}/summary?start_date=2026-06-29&end_date=2026-07-05").json()
    assert body["period"] == "week"
    assert len(body["periods"]) == 1
    wk = body["periods"][0]

    assert wk["period_start"] == "2026-06-29"
    assert wk["period_end"] == "2026-07-05"
    assert wk["days_logged"] == 2
    assert wk["days_in_period"] == 7
    assert wk["nutrition"]["energy_kcal"] == 2200.0  # (2000 + 2400) / 2
    assert wk["nutrition"]["protein_g"] == 120.0
    assert wk["nutrition"]["fiber_g"] is None  # never reported
    assert wk["body"]["weight_avg"] == 69.75
    assert wk["body"]["weight_change"] == -0.5
    assert wk["protein_g_per_kg"] == round(120.0 / 69.75, 2)
    assert wk["training"] == {
        "workouts": 1,
        "distance_km": 12.0,
        "duration_min": 60.0,
        "energy_kcal": 800.0,
    }


def test_summary_excludes_partial_days_from_averages(client_a):
    client_a.post(
        BASE,
        json={
            "days": [
                day_payload("2026-06-29", energy_kcal=2400),
                day_payload("2026-06-30", energy_kcal=600, partial=True),
            ]
        },
    )
    wk = client_a.get(f"{BASE}/summary?start_date=2026-06-29&end_date=2026-07-05").json()["periods"][0]
    assert wk["nutrition"]["energy_kcal"] == 2400.0
    assert wk["days_logged"] == 1
    assert wk["days_partial"] == 1


def test_summary_rejects_inverted_range(client_a):
    resp = client_a.get(f"{BASE}/summary?start_date=2026-07-10&end_date=2026-07-01")
    assert resp.status_code == 400


def test_summary_rejects_unknown_timezone(client_a):
    resp = client_a.get(f"{BASE}/summary?start_date=2026-07-01&timezone=Mars/Olympus")
    assert resp.status_code == 400


def test_summary_timezone_attributes_workout_to_local_day(client_a, session_factory, user_a):
    """A 00:30 local workout in UTC+2 is 22:30 the previous UTC day — with a
    timezone it belongs to the week the athlete actually ran it in."""
    with session_factory() as db:
        db.add(
            Workout(
                id="22222222-2222-2222-2222-222222222222",
                user_id=user_a[0],
                activity_type="running",
                # 2026-07-06 00:30 Europe/Amsterdam == 2026-07-05 22:30 UTC
                start_date=datetime(2026, 7, 5, 22, 30, tzinfo=timezone.utc),
                end_date=datetime(2026, 7, 5, 23, 0, tzinfo=timezone.utc),
                duration=1800,
                total_distance=6000,
                source="test",
                data={},
            )
        )
        db.commit()

    url = f"{BASE}/summary?start_date=2026-06-29&end_date=2026-07-12"
    utc_weeks = {p["period_start"]: p["training"]["workouts"] for p in client_a.get(url).json()["periods"]}
    assert utc_weeks["2026-06-29"] == 1  # UTC date 07-05 → week starting 06-29

    local = client_a.get(f"{url}&timezone=Europe/Amsterdam").json()["periods"]
    local_weeks = {p["period_start"]: p["training"]["workouts"] for p in local}
    assert local_weeks["2026-07-06"] == 1  # local date 07-06 → the next week
    assert local_weeks["2026-06-29"] == 0


def test_summary_month_period(client_a):
    client_a.post(
        BASE,
        json={
            "days": [
                day_payload("2026-06-15", energy_kcal=2000),
                day_payload("2026-07-15", energy_kcal=2600),
            ]
        },
    )
    body = client_a.get(f"{BASE}/summary?start_date=2026-06-01&end_date=2026-07-31&period=month").json()
    periods = body["periods"]
    assert [p["period_start"] for p in periods] == ["2026-07-01", "2026-06-01"]  # newest first
    assert periods[0]["nutrition"]["energy_kcal"] == 2600.0
    assert periods[1]["nutrition"]["energy_kcal"] == 2000.0
    assert periods[1]["days_in_period"] == 30


# ── pure summariser ────────────────────────────────────────────────────────


def test_bucket_boundaries():
    # 2026-07-01 is a Wednesday.
    assert bucket_start(date(2026, 7, 1), "week") == date(2026, 6, 29)
    assert bucket_end(date(2026, 6, 29), "week") == date(2026, 7, 5)
    assert bucket_start(date(2026, 7, 15), "month") == date(2026, 7, 1)
    assert bucket_end(date(2026, 2, 1), "month") == date(2026, 2, 28)  # non-leap
    assert bucket_end(date(2024, 2, 1), "month") == date(2024, 2, 29)  # leap
    with pytest.raises(ValueError):
        bucket_start(date(2026, 7, 1), "fortnight")


def test_summarize_clamps_edge_periods_to_window():
    """days_in_period reflects the requested window, so a half-week's average
    isn't read as a whole week's."""
    rows = summarize(
        [NutritionDay(day=date(2026, 7, 2), values={"energy_kcal": 2000}, partial=False)],
        [],
        [],
        start_date=date(2026, 7, 1),  # Wednesday
        end_date=date(2026, 7, 3),
        period="week",
    )
    assert len(rows) == 1
    assert rows[0]["period_start"] == date(2026, 7, 1)
    assert rows[0]["period_end"] == date(2026, 7, 3)
    assert rows[0]["days_in_period"] == 3


def test_summarize_emits_empty_periods():
    """Gaps must appear as zero-logged periods, not vanish — a missing week is
    itself information about adherence."""
    rows = summarize(
        [NutritionDay(day=date(2026, 6, 29), values={"energy_kcal": 2000})],
        [],
        [],
        start_date=date(2026, 6, 29),
        end_date=date(2026, 7, 12),
        period="week",
    )
    assert len(rows) == 2
    assert rows[0]["days_logged"] == 0  # newest week, nothing logged
    assert rows[0]["nutrition"]["energy_kcal"] is None
    assert rows[1]["days_logged"] == 1


def test_summarize_ignores_rows_outside_window():
    rows = summarize(
        [NutritionDay(day=date(2026, 6, 1), values={"energy_kcal": 9999})],
        [WeightPoint(day=date(2026, 6, 1), weight=99.0)],
        [WorkoutLoad(day=date(2026, 6, 1), distance_m=99000)],
        start_date=date(2026, 6, 29),
        end_date=date(2026, 7, 5),
        period="week",
    )
    assert rows[0]["days_logged"] == 0
    assert rows[0]["body"]["weight_avg"] is None
    assert rows[0]["training"]["workouts"] == 0


def test_summarize_single_weight_point_has_no_change():
    """One weigh-in is a value, not a trend."""
    rows = summarize(
        [], [WeightPoint(day=date(2026, 6, 30), weight=70.0)], [], date(2026, 6, 29), date(2026, 7, 5)
    )
    assert rows[0]["body"]["weight_avg"] == 70.0
    assert rows[0]["body"]["weight_change"] is None


def test_summarize_inverted_range_is_empty():
    assert summarize([], [], [], date(2026, 7, 5), date(2026, 7, 1)) == []


def test_summarize_averages_each_nutrient_over_its_own_present_days():
    """Protein logged on one of two days averages over that one day, not both —
    otherwise a sparsely tracked nutrient reads as a deficit."""
    rows = summarize(
        [
            NutritionDay(day=date(2026, 6, 29), values={"energy_kcal": 2000, "protein_g": 120}),
            NutritionDay(day=date(2026, 6, 30), values={"energy_kcal": 2200, "protein_g": None}),
        ],
        [],
        [],
        date(2026, 6, 29),
        date(2026, 7, 5),
    )
    assert rows[0]["nutrition"]["energy_kcal"] == 2100.0
    assert rows[0]["nutrition"]["protein_g"] == 120.0
    assert rows[0]["days_logged"] == 2


# ── energy expenditure / balance ────────────────────────────────────────────


WEEK = (date(2026, 6, 29), date(2026, 7, 5))


def _intake(day: date, kcal: float, partial: bool = False) -> NutritionDay:
    return NutritionDay(day=day, values={"energy_kcal": kcal}, partial=partial)


def test_expenditure_sums_active_and_basal_into_tdee():
    rows = summarize(
        [],
        [],
        [],
        *WEEK,
        energy=[
            EnergyDay(day=date(2026, 6, 29), active_kcal=1200, basal_kcal=1700),
            EnergyDay(day=date(2026, 6, 30), active_kcal=1000, basal_kcal=1700),
        ],
    )
    exp = rows[0]["expenditure"]
    assert exp["active_kcal_avg"] == 1100
    assert exp["basal_kcal_avg"] == 1700
    assert exp["tdee_kcal_avg"] == 2800
    assert exp["days_with_tdee"] == 2


def test_tdee_is_null_until_basal_arrives_but_active_still_reports():
    """The app ships basal after active. Until then the movement figure is
    still the useful half — it must not be withheld for want of a total."""
    rows = summarize(
        [],
        [],
        [],
        *WEEK,
        energy=[EnergyDay(day=date(2026, 6, 29), active_kcal=1200, basal_kcal=None)],
    )
    exp = rows[0]["expenditure"]
    assert exp["active_kcal_avg"] == 1200
    assert exp["days_with_energy"] == 1
    assert exp["basal_kcal_avg"] is None
    assert exp["tdee_kcal_avg"] is None
    assert exp["days_with_tdee"] == 0
    assert exp["balance_kcal_avg"] is None


def test_balance_pairs_intake_and_tdee_on_the_same_day():
    """Averaging intake and TDEE separately then subtracting would compare a
    1-day mean against a 2-day one. Only days holding both may contribute."""
    rows = summarize(
        [_intake(date(2026, 6, 29), 2400)],
        [],
        [],
        *WEEK,
        energy=[
            EnergyDay(day=date(2026, 6, 29), active_kcal=1200, basal_kcal=1700),
            # No intake logged this day: expenditure counts it, balance cannot.
            EnergyDay(day=date(2026, 6, 30), active_kcal=400, basal_kcal=1700),
        ],
    )
    exp = rows[0]["expenditure"]
    assert exp["days_with_tdee"] == 2
    assert exp["days_with_balance"] == 1
    assert exp["balance_kcal_avg"] == 2400 - 2900
    # The naive difference-of-averages would have been 2400 - 2500 = -100.
    assert exp["balance_kcal_avg"] != round(2400 - exp["tdee_kcal_avg"])


def test_partial_intake_day_is_excluded_from_balance():
    """A day synced mid-log holds a fraction of its intake and would read as a
    huge deficit — the same exclusion the nutrient averages already apply."""
    rows = summarize(
        [_intake(date(2026, 6, 29), 600, partial=True)],
        [],
        [],
        *WEEK,
        energy=[EnergyDay(day=date(2026, 6, 29), active_kcal=1200, basal_kcal=1700)],
    )
    exp = rows[0]["expenditure"]
    assert exp["days_with_tdee"] == 1
    assert exp["days_with_balance"] == 0
    assert exp["balance_kcal_avg"] is None


def test_complete_through_drops_the_day_still_in_progress():
    """Health metrics carry no partial flag: today holds only the hours
    elapsed, so a 300 kcal active day at 09:00 must not enter the average."""
    rows = summarize(
        [],
        [],
        [],
        *WEEK,
        energy=[
            EnergyDay(day=date(2026, 6, 29), active_kcal=1200, basal_kcal=1700),
            EnergyDay(day=date(2026, 6, 30), active_kcal=300, basal_kcal=500),
        ],
        complete_through=date(2026, 6, 29),
    )
    exp = rows[0]["expenditure"]
    assert exp["days_with_energy"] == 1
    assert exp["active_kcal_avg"] == 1200
    assert exp["tdee_kcal_avg"] == 2900


def test_expenditure_is_absent_energy_safe():
    """Every existing caller passes no energy at all; the block must still be
    present and null rather than missing."""
    rows = summarize([_intake(date(2026, 6, 29), 2400)], [], [], *WEEK)
    exp = rows[0]["expenditure"]
    assert exp["days_with_energy"] == 0
    assert exp["active_kcal_avg"] is None
    assert exp["tdee_kcal_avg"] is None
    assert exp["balance_kcal_avg"] is None


def test_active_energy_is_not_double_counted_with_workout_load():
    """active_kcal already contains the workout's burn. The training block
    reports the same calories from the other table; TDEE must ignore it."""
    rows = summarize(
        [],
        [],
        [WorkoutLoad(day=date(2026, 6, 29), energy_kcal=600)],
        *WEEK,
        energy=[EnergyDay(day=date(2026, 6, 29), active_kcal=1200, basal_kcal=1700)],
    )
    assert rows[0]["training"]["energy_kcal"] == 600
    assert rows[0]["expenditure"]["tdee_kcal_avg"] == 2900


def test_basal_round_trips_through_the_api(client_a):
    client_a.post(METRICS, json={"metrics": [
        {"date": "2026-07-01", "active_energy_burned": 1150.5, "basal_energy_burned": 1702.25},
    ]})
    rows = client_a.get(f"{METRICS}?start_date=2026-07-01&end_date=2026-07-01").json()
    assert rows[0]["basal_energy_burned"] == 1702.25
    assert rows[0]["active_energy_burned"] == 1150.5


def test_basal_omitted_does_not_erase_stored_value(client_a):
    """Same contract as every other metric column: an older app build syncing
    without basal must not wipe what a newer one wrote."""
    client_a.post(METRICS, json={"metrics": [
        {"date": "2026-07-02", "basal_energy_burned": 1700.0},
    ]})
    client_a.post(METRICS, json={"metrics": [
        {"date": "2026-07-02", "steps": 9000},
    ]})
    rows = client_a.get(f"{METRICS}?start_date=2026-07-02&end_date=2026-07-02").json()
    assert rows[0]["basal_energy_burned"] == 1700.0
    assert rows[0]["steps"] == 9000


def test_summary_endpoint_exposes_expenditure(client_a):
    today = date.today()
    day = today - timedelta(days=2)
    client_a.post(METRICS, json={"metrics": [
        {"date": day.isoformat(), "active_energy_burned": 1200, "basal_energy_burned": 1700},
    ]})
    client_a.post(BASE, json={"days": [{"date": day.isoformat(), "energy_kcal": 2400}]})
    body = client_a.get(
        f"{BASE}/summary?start_date={day.isoformat()}&period=week"
    ).json()
    exp = next(p["expenditure"] for p in body["periods"] if p["expenditure"]["days_with_energy"])
    assert exp["tdee_kcal_avg"] == 2900
    assert exp["balance_kcal_avg"] == -500


def test_summary_endpoint_excludes_today_from_expenditure(client_a):
    """Today's row is mid-day by construction; it must not drag the average."""
    today = date.today()
    client_a.post(METRICS, json={"metrics": [
        {"date": today.isoformat(), "active_energy_burned": 90, "basal_energy_burned": 200},
    ]})
    body = client_a.get(
        f"{BASE}/summary?start_date={today.isoformat()}&period=week"
    ).json()
    assert all(p["expenditure"]["days_with_energy"] == 0 for p in body["periods"])


# ── weight trend ────────────────────────────────────────────────────────────


def _w(day: int, kg: float) -> WeightPoint:
    return WeightPoint(day=date(2026, 7, day), weight=kg)


REAL_SERIES = [(25, 80.9), (27, 83.1), (28, 81.6), (29, 83.8), (30, 81.0), (31, 83.9)]


def test_weight_trend_beats_last_minus_first_on_the_real_series():
    """Six consecutive days alternating between two weigh-in conditions ~2.4 kg
    apart, with no underlying trend. Last-minus-first calls that +2.9 kg. The
    fit must land materially closer to flat — it does not reach flat, because
    the condition is confounded with time here, and that is what `sd` is for."""
    points = [_w(d, kg) for d, kg in REAL_SERIES]
    change, sd = weight_trend(points)

    naive = REAL_SERIES[-1][1] - REAL_SERIES[0][1]
    assert abs(change) < abs(naive) - 1.0, f"no better than differencing: {change} vs {naive}"

    # The honest part: the change has not separated from its own scatter, so a
    # reader with both numbers can see there is no trend here.
    assert sd is not None and abs(change) < 2 * sd


def test_weight_trend_tracks_a_real_gain_added_to_the_same_noise():
    """The fit must not be so smooth it flattens genuine change. Measured as a
    delta against the same series' own baseline, which isolates sensitivity to
    real movement from the confounding above."""
    baseline, _ = weight_trend([_w(d, kg) for d, kg in REAL_SERIES])
    shifted, _ = weight_trend(
        [_w(d, kg + 2.0 * (d - 25) / 6) for d, kg in REAL_SERIES]
    )
    assert 1.7 < shifted - baseline < 2.3, f"real trend lost: {shifted - baseline}"


def test_weight_trend_matches_endpoints_for_two_clean_readings():
    change, sd = weight_trend([_w(1, 80.0), _w(31, 78.0)])
    assert change == -2.0
    assert sd is None, "two points always fit perfectly; 0.0 scatter would be a lie"


def test_weight_trend_needs_a_span():
    assert weight_trend([]) == (None, None)
    assert weight_trend([_w(1, 80.0)]) == (None, None)
    # Two readings on the same day have no span to fit across.
    assert weight_trend([_w(1, 80.0), _w(1, 81.0)]) == (None, None)


def test_summary_reports_weigh_in_count_and_scatter():
    rows = summarize(
        [],
        [_w(29, 80.9), _w(30, 83.1), _w(31, 81.6)],
        [],
        date(2026, 7, 27),
        date(2026, 7, 31),
    )
    body = rows[0]["body"]
    assert body["weigh_ins"] == 3
    assert body["weight_sd"] is not None
    # Raw endpoints stay available; they're facts, just not the trend.
    assert body["weight_start"] == 80.9
    assert body["weight_end"] == 81.6


def test_summary_body_is_empty_safe():
    rows = summarize([], [], [], date(2026, 7, 27), date(2026, 7, 31))
    body = rows[0]["body"]
    assert body["weigh_ins"] == 0
    assert body["weight_change"] is None
    assert body["weight_sd"] is None
