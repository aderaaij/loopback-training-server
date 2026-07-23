"""Route tests for /api/health/sleep/* and the health-metrics transition guard.

The regression property that was actually violated in July 2026: syncing
partial windows at arbitrary times must never shrink an already-stored night.
"""

from datetime import date

from sqlalchemy import select

from app.models.health_metrics import DailyHealthMetrics

BASE = "/api/health/sleep"
METRICS = "/api/health/metrics"
TZ = "Europe/Amsterdam"
WATCH = "com.apple.health.watch"


def iso(day: int, hour: int, minute: int = 0) -> str:
    return f"2026-07-{day:02d}T{hour:02d}:{minute:02d}:00+02:00"


def sample(start: str, end: str, stage: str, source: str = WATCH) -> dict:
    return {"start": start, "end": end, "stage": stage, "source": source}


def night_payload() -> dict:
    """Bed 22:00 Jul 1 → up 06:30 Jul 2; 30000s asleep + 600s awake."""
    return {
        "timezone": TZ,
        "samples": [
            sample(iso(1, 22, 0), iso(1, 23, 30), "core"),
            sample(iso(1, 23, 30), iso(2, 0, 15), "deep"),
            sample(iso(2, 0, 15), iso(2, 1, 0), "rem"),
            sample(iso(2, 1, 0), iso(2, 1, 10), "awake"),
            sample(iso(2, 1, 10), iso(2, 6, 30), "core"),
        ],
    }


def get_day(client, day: str) -> dict | None:
    rows = client.get(f"{METRICS}?start_date=2026-06-25").json()
    return next((r for r in rows if r["date"] == day), None)


def test_upload_derives_rollup(client_a):
    r = client_a.post(f"{BASE}/samples", json=night_payload())
    assert r.status_code == 200
    body = r.json()
    assert body["received"] == 5 and body["stored"] == 5
    assert body["days_updated"] == ["2026-07-02"]

    day = get_day(client_a, "2026-07-02")
    assert day["sleep_duration"] == 30000
    assert day["sleep_stages"] == {"core": 24600, "deep": 2700, "rem": 2700, "awake": 600}


def test_reupload_is_true_noop(client_a):
    client_a.post(f"{BASE}/samples", json=night_payload())
    first = get_day(client_a, "2026-07-02")

    r = client_a.post(f"{BASE}/samples", json=night_payload())
    assert r.json()["stored"] == 0
    assert r.json()["days_updated"] == []
    second = get_day(client_a, "2026-07-02")
    assert second["updated_at"] == first["updated_at"]


def test_fragment_sync_never_shrinks_a_night(client_a):
    # An old-style partial window: the bedtime→midnight prefix of the night,
    # with the deep sample clipped at the window edge.
    fragment = {
        "timezone": TZ,
        "samples": [
            sample(iso(1, 22, 0), iso(1, 23, 30), "core"),
            sample(iso(1, 23, 30), iso(1, 23, 59), "deep"),
        ],
    }
    client_a.post(f"{BASE}/samples", json=fragment)
    assert get_day(client_a, "2026-07-02")["sleep_duration"] == 7140

    # Late samples arrive: the night completes.
    client_a.post(f"{BASE}/samples", json=night_payload())
    assert get_day(client_a, "2026-07-02")["sleep_duration"] == 30000

    # The fragment syncing again must not shrink it back.
    r = client_a.post(f"{BASE}/samples", json=fragment)
    assert r.json()["days_updated"] == []
    assert get_day(client_a, "2026-07-02")["sleep_duration"] == 30000


def test_inflation_scenario_never_sums(client_a):
    payload = night_payload()
    payload["samples"].append(sample(iso(1, 22, 0), iso(2, 6, 30), "unspecified", "com.thirdparty.sleep"))
    payload["samples"].append(sample(iso(1, 21, 45), iso(2, 6, 45), "in_bed", "com.apple.health.iphone"))
    client_a.post(f"{BASE}/samples", json=payload)
    assert get_day(client_a, "2026-07-02")["sleep_duration"] == 30000


def test_legacy_sleep_ignored_once_samples_exist(client_a):
    # Pre-samples: the legacy aggregate path still owns sleep.
    r = client_a.post(METRICS, json={"metrics": [{"date": "2026-07-02", "sleep_duration": 999, "steps": 100}]})
    assert r.status_code == 200
    assert get_day(client_a, "2026-07-02")["sleep_duration"] == 999

    # Samples arrive: derived rollup replaces it, and the rewrite is visible.
    client_a.post(f"{BASE}/samples", json=night_payload())
    day = get_day(client_a, "2026-07-02")
    assert day["sleep_duration"] == 30000
    assert day["updated_at"] > day["created_at"]

    # An old app build posting truncated aggregates can no longer clobber
    # sleep — but its other metrics still land.
    client_a.post(
        METRICS,
        json={
            "metrics": [
                {"date": "2026-07-02", "sleep_duration": 111, "sleep_stages": {"core": 111}, "steps": 5000}
            ]
        },
    )
    day = get_day(client_a, "2026-07-02")
    assert day["sleep_duration"] == 30000
    assert day["steps"] == 5000


def test_rederive_repairs_clobbered_rollup(client_a, user_a, session_factory):
    client_a.post(f"{BASE}/samples", json=night_payload())

    # Simulate historical corruption written before the guard existed.
    with session_factory() as db:
        row = db.scalar(
            select(DailyHealthMetrics).where(
                DailyHealthMetrics.user_id == user_a[0], DailyHealthMetrics.date == date(2026, 7, 2)
            )
        )
        row.sleep_duration = 1
        row.sleep_stages = {"core": 1}
        db.commit()

    body = {"start_date": "2026-07-01", "end_date": "2026-07-03", "timezone": TZ}
    r = client_a.post(f"{BASE}/rederive", json=body)
    assert r.json()["days_updated"] == ["2026-07-02"]
    assert get_day(client_a, "2026-07-02")["sleep_duration"] == 30000

    # Unchanged samples → rederive is a no-op.
    assert client_a.post(f"{BASE}/rederive", json=body).json()["days_updated"] == []


def test_samples_diagnostic_listing(client_a):
    client_a.post(f"{BASE}/samples", json=night_payload())
    rows = client_a.get(f"{BASE}/samples?start_date=2026-07-01").json()
    assert len(rows) == 5
    assert {r["source"] for r in rows} == {WATCH}
    assert client_a.get(f"{BASE}/samples?start_date=2026-07-03").json() == []


def test_user_isolation(client_a, client_b):
    client_a.post(f"{BASE}/samples", json=night_payload())
    assert client_b.get(f"{BASE}/samples?start_date=2026-07-01").json() == []
    assert get_day(client_b, "2026-07-02") is None


def test_rejects_bad_input(client_a):
    good = sample(iso(1, 22, 0), iso(1, 23, 0), "core")
    cases = [
        {"timezone": "Mars/Olympus_Mons", "samples": [good]},
        {"timezone": TZ, "samples": [sample("2026-07-01T22:00:00", "2026-07-01T23:00:00", "core")]},  # naive
        {"timezone": TZ, "samples": [sample(iso(1, 23, 0), iso(1, 22, 0), "core")]},  # end before start
        {"timezone": TZ, "samples": [sample(iso(1, 22, 0), iso(1, 23, 0), "snoring")]},  # unknown stage
        {"timezone": TZ, "samples": []},
    ]
    for body in cases:
        assert client_a.post(f"{BASE}/samples", json=body).status_code == 422, body
