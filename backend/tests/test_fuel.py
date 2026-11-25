"""Fuelling: saved products, the log on a workout and the plan on a session."""

import uuid

PRODUCTS = "/api/fuel/products"
HISTORY = "/api/fuel/history"
CONSENT = "/api/me/data-consent"
COACH = {"X-Consent-Scope": "coach"}

SCHEDULED = "2026-11-22T08:00:00+00:00"


def make_product(client, name="Gel 30", kind="gel", **extra):
    r = client.post(PRODUCTS, json={"name": name, "kind": kind, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def make_session(client, title="Long run 26k"):
    r = client.post(
        "/api/queue",
        json={
            "activityType": "running",
            "title": title,
            "scheduledDate": SCHEDULED,
            "workoutData": {"displayName": title, "scheduledDate": SCHEDULED},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_workout(client, duration=7200, distance=24_000, session_id=None, start="2026-11-22T08:05:00+00:00"):
    payload = {
        "id": str(uuid.uuid4()),
        "activityType": "running",
        "startDate": start,
        "endDate": "2026-11-22T10:05:00+00:00",
        "duration": duration,
        "totalDistance": distance,
    }
    if session_id:
        payload["planWorkoutId"] = session_id
    r = client.post("/api/workouts", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def log(workout_id):
    return f"/api/workouts/{workout_id}/fuel"


def plan(session_id):
    return f"/api/workouts/queue/{session_id}/fuel"


# ── products ────────────────────────────────────────────────────────────────


def test_a_product_is_saved_with_its_figures(client_a):
    gel = make_product(client_a, "Caffeine gel", carbsG=30, caffeineMg=100)
    assert gel["kind"] == "gel"
    assert gel["carbsG"] == 30
    assert gel["caffeineMg"] == 100
    assert gel["volumeMl"] is None


def test_products_list_drinks_first_then_by_name(client_a):
    make_product(client_a, "gel 30")
    make_product(client_a, "Water", kind="drink", volumeMl=500)
    make_product(client_a, "Chews", kind="other")
    make_product(client_a, "Electrolytes", kind="drink", volumeMl=500, carbsG=40)
    assert [p["name"] for p in client_a.get(PRODUCTS).json()] == ["Electrolytes", "Water", "Chews", "gel 30"]


def test_only_a_drink_keeps_a_serving_volume(client_a):
    assert make_product(client_a, "Gel", volumeMl=60)["volumeMl"] is None
    drink = make_product(client_a, "Mix", kind="drink", volumeMl=500)
    r = client_a.patch(f"{PRODUCTS}/{drink['id']}", json={"kind": "gel"})
    assert r.json()["volumeMl"] is None


def test_a_product_is_changed_field_by_field(client_a):
    gel = make_product(client_a, carbsG=30, caffeineMg=100)
    r = client_a.patch(f"{PRODUCTS}/{gel['id']}", json={"name": "Gel 30 (new)", "caffeineMg": None})
    assert r.status_code == 200
    assert r.json()["name"] == "Gel 30 (new)"
    assert r.json()["caffeineMg"] is None
    assert r.json()["carbsG"] == 30


def test_a_product_needs_a_name_and_a_known_kind(client_a):
    assert client_a.post(PRODUCTS, json={"name": "  ", "kind": "gel"}).status_code == 422
    assert client_a.post(PRODUCTS, json={"name": "Bar", "kind": "sandwich"}).status_code == 422


# ── a workout's log ─────────────────────────────────────────────────────────


def test_a_workout_starts_with_nothing_logged(client_a):
    body = client_a.get(log(make_workout(client_a))).json()
    assert body["entries"] == []
    assert body["planned"] == []
    assert body["plannedSummary"] is None
    assert body["plannedSessionId"] is None
    assert body["summary"] == {
        "volumeMl": 0,
        "carbsG": 0,
        "caffeineMg": 0,
        "carbsPerHourG": 0,
        "fluidPerHourMl": 0,
    }


def test_an_entry_takes_its_name_and_figures_from_its_product(client_a):
    gel = make_product(client_a, "Caffeine gel", carbsG=30, caffeineMg=100)
    workout = make_workout(client_a)
    r = client_a.post(log(workout), json={"productId": gel["id"], "atDistance": 7000})
    assert r.status_code == 201, r.text
    (entry,) = r.json()["entries"]
    assert entry["name"] == "Caffeine gel"
    assert entry["kind"] == "gel"
    assert entry["carbsG"] == 30
    assert entry["caffeineMg"] == 100
    assert entry["atDistance"] == 7000
    assert entry["productId"] == gel["id"]


def test_a_drinks_figures_follow_the_volume_drunk(client_a):
    mix = make_product(client_a, "Electrolytes", kind="drink", volumeMl=500, carbsG=40, caffeineMg=0)
    workout = make_workout(client_a)
    (entry,) = client_a.post(log(workout), json={"productId": mix["id"], "volumeMl": 750}).json()["entries"]
    assert entry["volumeMl"] == 750
    assert entry["carbsG"] == 60
    assert entry["caffeineMg"] == 0

    # With no volume given, one serving.
    other = make_workout(client_a)
    (entry,) = client_a.post(log(other), json={"productId": mix["id"]}).json()["entries"]
    assert entry["volumeMl"] == 500
    assert entry["carbsG"] == 40


def test_figures_that_are_sent_win_over_the_products(client_a):
    gel = make_product(client_a, carbsG=30, caffeineMg=100)
    workout = make_workout(client_a)
    (entry,) = client_a.post(
        log(workout), json={"productId": gel["id"], "name": "Half a gel", "carbsG": 15, "caffeineMg": None}
    ).json()["entries"]
    assert entry["name"] == "Half a gel"
    assert entry["carbsG"] == 15
    assert entry["caffeineMg"] is None


def test_an_entry_without_a_product_needs_a_name_and_a_kind(client_a):
    workout = make_workout(client_a)
    assert client_a.post(log(workout), json={"name": "Banana"}).status_code == 422
    assert client_a.post(log(workout), json={"kind": "other"}).status_code == 422
    r = client_a.post(log(workout), json={"name": "Banana", "kind": "other", "carbsG": 25, "atDistance": 15_000})
    assert r.status_code == 201
    assert r.json()["entries"][0]["productId"] is None


def test_an_unknown_product_is_refused(client_a, client_b):
    theirs = make_product(client_b)
    workout = make_workout(client_a)
    assert client_a.post(log(workout), json={"productId": theirs["id"]}).status_code == 422
    assert client_a.post(log(workout), json={"productId": str(uuid.uuid4())}).status_code == 422


def test_the_log_is_ordered_drinks_first_then_by_where_it_was_taken(client_a):
    workout = make_workout(client_a)
    r = client_a.put(
        log(workout),
        json={
            "entries": [
                {"name": "Gel", "kind": "gel", "atDistance": 15_000},
                {"name": "Salt tab", "kind": "other"},
                {"name": "Gel", "kind": "gel", "atDistance": 7000},
                {"name": "Water", "kind": "drink", "volumeMl": 500},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert [(e["name"], e["atDistance"]) for e in r.json()["entries"]] == [
        ("Water", None),
        ("Gel", 7000),
        ("Gel", 15_000),
        ("Salt tab", None),
    ]


def test_totals_and_hourly_rates_come_from_the_entries(client_a):
    workout = make_workout(client_a, duration=7200)
    r = client_a.put(
        log(workout),
        json={
            "entries": [
                {"name": "Water", "kind": "drink", "volumeMl": 500},
                {"name": "Electrolytes", "kind": "drink", "volumeMl": 500, "carbsG": 40},
                {"name": "Caffeine gel", "kind": "gel", "carbsG": 30, "caffeineMg": 100, "atDistance": 7000},
                {"name": "Gel", "kind": "gel", "carbsG": 30, "atDistance": 15_000},
            ]
        },
    )
    assert r.json()["summary"] == {
        "volumeMl": 1000,
        "carbsG": 100,
        "caffeineMg": 100,
        "carbsPerHourG": 50,
        "fluidPerHourMl": 500,
    }


def test_a_short_workout_has_no_hourly_rate(client_a):
    workout = make_workout(client_a, duration=600)
    summary = client_a.post(log(workout), json={"name": "Gel", "kind": "gel", "carbsG": 30}).json()["summary"]
    assert summary["carbsG"] == 30
    assert summary["carbsPerHourG"] is None
    assert summary["fluidPerHourMl"] is None


def test_replacing_the_log_replaces_all_of_it_and_empty_clears_it(client_a):
    workout = make_workout(client_a)
    client_a.post(log(workout), json={"name": "Gel", "kind": "gel"})
    r = client_a.put(log(workout), json={"entries": [{"name": "Water", "kind": "drink", "volumeMl": 300}]})
    assert [e["name"] for e in r.json()["entries"]] == ["Water"]
    assert client_a.put(log(workout), json={"entries": []}).json()["entries"] == []


def test_a_bad_entry_leaves_the_log_as_it_was(client_a):
    workout = make_workout(client_a)
    client_a.post(log(workout), json={"name": "Gel", "kind": "gel"})
    r = client_a.put(log(workout), json={"entries": [{"name": "Water", "kind": "drink"}, {"name": "No kind"}]})
    assert r.status_code == 422
    assert [e["name"] for e in client_a.get(log(workout)).json()["entries"]] == ["Gel"]


def test_changing_or_deleting_a_product_leaves_what_was_logged(client_a):
    gel = make_product(client_a, "Gel 30", carbsG=30)
    workout = make_workout(client_a)
    client_a.post(log(workout), json={"productId": gel["id"], "atDistance": 7000})

    client_a.patch(f"{PRODUCTS}/{gel['id']}", json={"name": "Gel 40", "carbsG": 40})
    (entry,) = client_a.get(log(workout)).json()["entries"]
    assert (entry["name"], entry["carbsG"]) == ("Gel 30", 30)

    assert client_a.delete(f"{PRODUCTS}/{gel['id']}").status_code == 204
    (entry,) = client_a.get(log(workout)).json()["entries"]
    assert (entry["name"], entry["carbsG"], entry["productId"]) == ("Gel 30", 30, None)


def test_deleting_a_workout_takes_its_log_with_it(client_a):
    workout = make_workout(client_a)
    client_a.post(log(workout), json={"name": "Gel", "kind": "gel"})
    assert client_a.delete(f"/api/workouts/{workout}").status_code == 204
    assert client_a.get(HISTORY).json() == []


# ── a session's plan ────────────────────────────────────────────────────────


def test_a_session_carries_a_plan(client_a):
    gel = make_product(client_a, carbsG=30)
    session = make_session(client_a)
    r = client_a.put(
        plan(session),
        json={
            "entries": [
                {"name": "Water", "kind": "drink", "volumeMl": 750},
                {"productId": gel["id"], "atDistance": 8000},
                {"productId": gel["id"], "atDistance": 16_000},
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [e["atDistance"] for e in body["entries"]] == [None, 8000, 16_000]
    # A plan has no duration to divide by.
    assert body["summary"] == {
        "volumeMl": 750,
        "carbsG": 60,
        "caffeineMg": 0,
        "carbsPerHourG": None,
        "fluidPerHourMl": None,
    }
    assert client_a.get(plan(session)).json() == body


def test_a_workout_shows_the_plan_of_the_session_it_counts_for(client_a):
    session = make_session(client_a)
    client_a.put(plan(session), json={"entries": [{"name": "Gel", "kind": "gel", "carbsG": 30, "atDistance": 8000}]})
    workout = make_workout(client_a, duration=7200, session_id=session)

    body = client_a.get(log(workout)).json()
    assert body["entries"] == []
    assert [(e["name"], e["atDistance"]) for e in body["planned"]] == [("Gel", 8000)]
    assert body["plannedSessionId"] == session
    # The plan's rate uses the workout's duration, so it compares with the log's.
    assert body["plannedSummary"]["carbsPerHourG"] == 15

    # The plan and the log are separate lists: logging does not touch the plan.
    client_a.post(log(workout), json={"name": "Gel", "kind": "gel", "carbsG": 30, "atDistance": 9500})
    assert len(client_a.get(plan(session)).json()["entries"]) == 1
    assert len(client_a.get(log(workout)).json()["entries"]) == 1


def test_a_workout_linked_to_a_session_without_a_plan_shows_none(client_a):
    workout = make_workout(client_a, session_id=make_session(client_a))
    body = client_a.get(log(workout)).json()
    assert body["planned"] == []
    assert body["plannedSessionId"] is None


def test_deleting_a_session_takes_its_plan_with_it(client_a):
    session = make_session(client_a)
    client_a.post(plan(session), json={"name": "Gel", "kind": "gel"})
    workout = make_workout(client_a, session_id=session)
    assert client_a.delete(f"/api/queue/{session}").status_code == 204
    assert client_a.get(log(workout)).json()["planned"] == []


# ── across workouts ─────────────────────────────────────────────────────────


def test_history_lists_logged_workouts_newest_first(client_a):
    older = make_workout(client_a, start="2026-11-08T08:00:00+00:00")
    newer = make_workout(client_a, start="2026-11-15T08:00:00+00:00", distance=26_000)
    make_workout(client_a, start="2026-11-20T08:00:00+00:00")  # nothing logged
    client_a.post(log(older), json={"name": "Gel", "kind": "gel", "carbsG": 30})
    client_a.post(log(newer), json={"name": "Water", "kind": "drink", "volumeMl": 500})

    history = client_a.get(HISTORY).json()
    assert [h["workoutId"] for h in history] == [newer, older]
    assert history[0]["totalDistance"] == 26_000
    assert history[0]["summary"]["volumeMl"] == 500
    assert history[1]["entries"][0]["name"] == "Gel"
    assert len(client_a.get(HISTORY, params={"limit": 1}).json()) == 1


# ── whose it is, and who may read it ────────────────────────────────────────


def test_fuelling_is_private_to_its_athlete(client_a, client_b):
    product = make_product(client_a)
    workout = make_workout(client_a)
    session = make_session(client_a)
    client_a.post(log(workout), json={"name": "Gel", "kind": "gel"})

    assert client_b.get(PRODUCTS).json() == []
    assert client_b.get(HISTORY).json() == []
    assert client_b.get(log(workout)).status_code == 404
    assert client_b.get(plan(session)).status_code == 404
    assert client_b.post(log(workout), json={"name": "Gel", "kind": "gel"}).status_code == 404
    assert client_b.put(plan(session), json={"entries": []}).status_code == 404
    assert client_b.patch(f"{PRODUCTS}/{product['id']}", json={"name": "Mine"}).status_code == 404
    assert client_b.delete(f"{PRODUCTS}/{product['id']}").status_code == 404


def test_the_coach_only_reads_fuelling_when_nutrition_is_shared(client_a):
    workout = make_workout(client_a)
    session = make_session(client_a)
    client_a.post(log(workout), json={"name": "Gel", "kind": "gel"})

    # Shared by default.
    assert client_a.get(log(workout), headers=COACH).status_code == 200

    assert client_a.put(CONSENT, json={"domains": ["training", "recovery"]}).status_code == 200
    for path in (PRODUCTS, HISTORY, log(workout), plan(session)):
        r = client_a.get(path, headers=COACH)
        assert r.status_code == 403, path
        assert "does not share" in r.json()["detail"]
    assert client_a.post(log(workout), json={"name": "Gel", "kind": "gel"}, headers=COACH).status_code == 403
    assert client_a.put(plan(session), json={"entries": []}, headers=COACH).status_code == 403

    # The athlete's own app is never filtered.
    assert len(client_a.get(log(workout)).json()["entries"]) == 1
