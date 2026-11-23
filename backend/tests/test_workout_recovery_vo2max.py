"""Heart rate recovery and VO2 max on a workout: stored from the upload,
returned on reads, and VO2 max hidden from the coach when `body` is withheld."""

import uuid
from datetime import datetime, timedelta, timezone

WORKOUTS = "/api/workouts"
CONSENT = "/api/me/data-consent"
COACH = {"X-Consent-Scope": "coach"}


def upload(client, workout_id=None, **extra):
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    payload = {
        "id": workout_id or str(uuid.uuid4()),
        "activityType": "running",
        "startDate": start.isoformat(),
        "endDate": (start + timedelta(minutes=50)).isoformat(),
        "duration": 3000,
        "totalDistance": 10_000.0,
        **extra,
    }
    r = client.post(WORKOUTS, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


FIGURES = {"endHeartRate": 171, "heartRateAfter1Min": 139, "heartRateAfter2Min": 121, "vo2Max": 52.3}


def test_figures_are_stored_as_columns_not_in_the_blob(client_a):
    run = upload(client_a, **FIGURES)
    assert run["end_heart_rate"] == 171
    assert run["heart_rate_after_1min"] == 139
    assert run["heart_rate_after_2min"] == 121
    assert run["vo2_max"] == 52.3
    assert not {"endHeartRate", "heartRateAfter1Min", "heartRateAfter2Min", "vo2Max"} & run["data"].keys()


def test_figures_are_on_the_list_and_the_detail(client_a):
    run = upload(client_a, **FIGURES)
    listed = next(w for w in client_a.get(WORKOUTS).json() if w["id"] == run["id"])
    assert listed["heart_rate_after_1min"] == 139
    assert listed["vo2_max"] == 52.3
    detail = client_a.get(f"{WORKOUTS}/{run['id']}", params={"include_samples": False}).json()
    assert detail["end_heart_rate"] == 171
    assert detail["vo2_max"] == 52.3


def test_a_workout_without_them_reads_null(client_a):
    run = upload(client_a)
    for field in ("end_heart_rate", "heart_rate_after_1min", "heart_rate_after_2min", "vo2_max"):
        assert run[field] is None


def test_a_later_upload_fills_them_in(client_a):
    """The watch hands the minutes after a workout to the phone late, so the
    app sends the workout again once they are there."""
    run = upload(client_a)
    again = upload(client_a, workout_id=run["id"], **FIGURES)
    assert again["heart_rate_after_2min"] == 121
    assert again["vo2_max"] == 52.3


def test_coach_sees_vo2_max_only_when_body_is_shared(client_a):
    run = upload(client_a, **FIGURES)
    url = f"{WORKOUTS}/{run['id']}"

    assert client_a.get(url, headers=COACH).json()["vo2_max"] == 52.3

    client_a.put(CONSENT, json={"domains": ["training", "recovery"]})
    for params in ({}, {"include_samples": False}):
        scoped = client_a.get(url, params=params, headers=COACH).json()
        assert scoped["vo2_max"] is None
        # Recovery heart rate is workout heart rate, which is always shared.
        assert scoped["heart_rate_after_1min"] == 139
    listed = next(w for w in client_a.get(WORKOUTS, headers=COACH).json() if w["id"] == run["id"])
    assert listed["vo2_max"] is None
    assigned = client_a.put(f"{url}/shoe", json={"shoeId": None}, headers=COACH).json()
    assert assigned["vo2_max"] is None

    # The athlete's own reads are never filtered.
    assert client_a.get(url).json()["vo2_max"] == 52.3
