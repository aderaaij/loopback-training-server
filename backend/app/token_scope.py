"""The two kinds of API token, and what the narrower one may call.

A `full` token is the athlete: the dashboard's session, the phone, a script
of their own. A `coach` token is what an assistant holds, whether it signed
in (app/oauth.py) or was pasted from the dashboard's Connect dialog. It lives
on someone else's servers or in a config file, so it is held to what the
coach does:

- it is refused on every route that is not in `COACH_ROUTES` below, checked in
  `get_current_user` (app/auth.py), the one place every authenticated request
  passes through. A route added later is therefore closed to it until someone
  lists it here;
- what the athlete shares with the coach is applied to it whether or not the
  `X-Consent-Scope` header is sent (app/data_consent.py).

So with a coach token nobody can create or revoke tokens, change what is
shared, approve another assistant, or upload data as if they were the phone.
It can still do everything the coach's tools can, which includes deleting a
workout and rewriting a plan.

`COACH_ROUTES` is exactly the set of requests the coach's own client makes
(`mcp/training_mcp/services/api_client.py`). `tests/test_token_scope.py`
reads that file and fails when the two differ in either direction: a tool
that calls something unlisted would work with a full token and answer 403
for everyone who signed in, and an entry nothing uses is access for no
reason. An entry is the request method and the route's path as it is
registered, parameter names included.
"""

FULL = "full"
COACH = "coach"
SCOPES: tuple[str, ...] = (FULL, COACH)

COACH_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        # What the athlete shares; read to decide which tools to offer.
        ("GET", "/api/me/data-consent"),
        # Workouts
        ("GET", "/api/workouts"),
        ("GET", "/api/workouts/summary"),
        ("GET", "/api/workouts/{workout_id}"),
        ("DELETE", "/api/workouts/{workout_id}"),
        ("GET", "/api/workouts/{workout_id}/context"),
        ("GET", "/api/workouts/{workout_id}/heartrate"),
        ("GET", "/api/workouts/{workout_id}/splits"),
        ("PUT", "/api/workouts/{workout_id}/shoe"),
        ("GET", "/api/workouts/{workout_id}/fuel"),
        ("POST", "/api/workouts/{workout_id}/fuel"),
        ("PUT", "/api/workouts/{workout_id}/fuel"),
        # What is on the watch, and changes to it
        ("GET", "/api/workouts/inventory"),
        ("GET", "/api/workouts/feedback"),
        ("GET", "/api/workouts/actions"),
        ("POST", "/api/workouts/actions"),
        ("POST", "/api/workouts/actions/batch"),
        ("GET", "/api/workouts/queue/{item_id}/fuel"),
        ("PUT", "/api/workouts/queue/{item_id}/fuel"),
        # Scheduled workouts
        ("GET", "/api/queue"),
        ("POST", "/api/queue"),
        ("POST", "/api/queue/batch"),
        ("GET", "/api/queue/pending"),
        ("PATCH", "/api/queue/{item_id}"),
        ("PATCH", "/api/queue/{item_id}/status"),
        # Plans and their strength schedule
        ("GET", "/api/plans"),
        ("POST", "/api/plans"),
        ("GET", "/api/plans/{plan_id}"),
        ("PATCH", "/api/plans/{plan_id}"),
        ("GET", "/api/plans/{plan_id}/workouts"),
        ("POST", "/api/plans/{plan_id}/validate"),
        ("GET", "/api/plans/{plan_id}/schedule"),
        ("PUT", "/api/plans/{plan_id}/schedule"),
        ("DELETE", "/api/plans/{plan_id}/schedule"),
        ("POST", "/api/plans/{plan_id}/schedule/sessions"),
        ("DELETE", "/api/plans/{plan_id}/schedule/sessions/{day}"),
        ("POST", "/api/plans/{plan_id}/schedule/sessions/{day}/move"),
        ("GET", "/api/schedule/calendar"),
        # Notes
        ("GET", "/api/plan-notes"),
        ("POST", "/api/plan-notes"),
        ("GET", "/api/plan-notes/context"),
        ("PATCH", "/api/plan-notes/{note_id}"),
        ("DELETE", "/api/plan-notes/{note_id}"),
        # Health, nutrition, fuelling
        ("GET", "/api/health/metrics"),
        ("GET", "/api/nutrition"),
        ("GET", "/api/nutrition/summary"),
        ("GET", "/api/fuel/history"),
        ("GET", "/api/fuel/products"),
        ("POST", "/api/fuel/products"),
        # Shoes
        ("GET", "/api/shoes"),
        ("POST", "/api/shoes"),
        ("PATCH", "/api/shoes/{shoe_id}"),
        # Illness and injury
        ("GET", "/api/setbacks"),
        ("POST", "/api/setbacks"),
        ("PATCH", "/api/setbacks/{setback_id}"),
        ("PUT", "/api/setbacks/{setback_id}/checkins/{day}"),
    }
)


def coach_may(method: str, route_path: str | None) -> bool:
    """Whether a coach token may make this request.

    `route_path` is the matched route's own path (`/api/plans/{plan_id}`), not
    the address that was asked for, so there is nothing in it a caller can
    shape. No matched route means no.
    """
    return (method.upper(), route_path) in COACH_ROUTES
