"""HTTP client for Training API."""

import logging
from typing import Any

import httpx
from fastmcp.server.dependencies import get_http_headers

from app.config import settings

logger = logging.getLogger(__name__)


class TrainingClient:
    """Client for interacting with Training REST API."""

    def __init__(self) -> None:
        self.base_url = settings.training_api_url.rstrip("/")
        self.timeout = settings.request_timeout
        self._api_key = settings.training_api_key.get_secret_value()

    def _resolve_auth(self) -> str:
        """Resolve the Authorization header for this request.

        An Authorization header on the incoming MCP request is forwarded as-is,
        so each caller acts as their own Training API user. Any presented header
        disables the fallback — a malformed credential must fail, not silently
        act as the fallback user. Outside an HTTP request context (stdio) or
        with no header, the env token is used unless REQUIRE_AUTH_HEADER is set.
        """
        # get_http_headers() strips `authorization` unless explicitly included
        incoming = get_http_headers(include={"authorization"}).get("authorization", "").strip()
        if incoming:
            return incoming
        if settings.require_auth_header:
            raise ValueError(
                "This MCP requires a per-user token: send an 'Authorization: Bearer "
                "<training-api token>' header with the request."
            )
        if not self._api_key:
            from app.config import Settings

            env_file = Settings.model_config.get("env_file")
            raise ValueError(
                f"No Authorization header on the request and TRAINING_API_KEY is not set (expected in: {env_file})"
            )
        return f"Bearer {self._api_key}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> list | dict:
        """Make an HTTP request to the Training API."""
        headers = {
            "Authorization": self._resolve_auth(),
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}{path}"
        logger.debug(f"Making {method} request to {url}")

        async with httpx.AsyncClient(timeout=self.timeout) as http_client:
            response = await http_client.request(
                method=method,
                url=url,
                headers=headers,
                **kwargs,
            )

            if response.status_code == 401:
                raise ValueError("Training API rejected the token (invalid, expired, or revoked).")
            if response.status_code == 404:
                raise ValueError(f"Resource not found: {path}")

            response.raise_for_status()
            return response.json()

    async def list_workouts(
        self,
        activity_type: str | None = None,
        start_after: str | None = None,
        start_before: str | None = None,
        limit: int = 50,
    ) -> list | dict:
        """List workouts with optional filters."""
        params: dict[str, Any] = {"limit": limit}
        if activity_type:
            params["activity_type"] = activity_type
        if start_after:
            params["start_after"] = start_after
        if start_before:
            params["start_before"] = start_before
        return await self._request("GET", "/api/workouts", params=params)

    async def get_workout(self, workout_id: str) -> list | dict:
        """Get a single workout by ID."""
        return await self._request("GET", f"/api/workouts/{workout_id}")

    async def delete_workout(self, workout_id: str) -> dict:
        """Delete a workout by ID."""
        self._ensure_configured()
        url = f"{self.base_url}/api/workouts/{workout_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as http_client:
            response = await http_client.request("DELETE", url, headers=self.headers)
            if response.status_code == 404:
                raise ValueError(f"Workout not found: {workout_id}")
            response.raise_for_status()
            return {"deleted": workout_id}

    async def get_workout_splits(self, workout_id: str) -> list | dict:
        """Get splits for a workout."""
        return await self._request("GET", f"/api/workouts/{workout_id}/splits")

    async def get_workout_heartrate(self, workout_id: str) -> list | dict:
        """Get heart rate samples for a workout."""
        return await self._request("GET", f"/api/workouts/{workout_id}/heartrate")

    async def get_workout_summary(
        self,
        activity_type: str | None = None,
        period: str = "month",
    ) -> list | dict:
        """Get workout summary grouped by period."""
        params: dict[str, Any] = {"period": period}
        if activity_type:
            params["activity_type"] = activity_type
        return await self._request("GET", "/api/workouts/summary", params=params)

    async def get_pending_queue(self) -> list | dict:
        """Get pending queue items."""
        return await self._request("GET", "/api/queue/pending")

    async def list_queue(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list | dict:
        """List queue items with optional status filter."""
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        return await self._request("GET", "/api/queue", params=params)

    async def create_queue_item(
        self,
        activity_type: str,
        title: str,
        description: str | None = None,
        workout_data: dict | None = None,
        plan_id: str | None = None,
    ) -> list | dict:
        """Create a new queue item. Sends camelCase keys as required by the API."""
        body: dict[str, Any] = {
            "activityType": activity_type,
            "title": title,
        }
        if description is not None:
            body["description"] = description
        if workout_data is not None:
            body["workoutData"] = workout_data
        if plan_id is not None:
            body["planId"] = plan_id
        return await self._request("POST", "/api/queue", json=body)

    async def update_queue_item(self, item_id: str, **fields: Any) -> list | dict:
        """Update a queue item's fields."""
        body: dict[str, Any] = {}
        key_map = {
            "activity_type": "activityType",
            "title": "title",
            "description": "description",
            "workout_data": "workoutData",
            "plan_id": "planId",
        }
        for key, value in fields.items():
            if value is not None and key in key_map:
                body[key_map[key]] = value
        return await self._request("PATCH", f"/api/queue/{item_id}", json=body)

    async def update_queue_status(self, item_id: str, status: str) -> list | dict:
        """Update the status of a queue item."""
        return await self._request("PATCH", f"/api/queue/{item_id}/status", json={"status": status})

    async def get_inventory(self) -> list | dict:
        """Get the on-device workout inventory."""
        return await self._request("GET", "/api/workouts/inventory")

    async def get_pending_actions(self) -> list | dict:
        """Get pending workout actions (edits/deletes)."""
        return await self._request("GET", "/api/workouts/actions")

    async def create_action(
        self,
        workout_id: str,
        action: str,
        composition: dict | None = None,
    ) -> list | dict:
        """Create a workout action (edit or delete)."""
        body: dict[str, Any] = {
            "workoutId": workout_id,
            "action": action,
        }
        if composition is not None:
            body["composition"] = composition
        return await self._request("POST", "/api/workouts/actions", json=body)

    async def get_feedback(
        self,
        since: str | None = None,
        limit: int = 20,
        action: str | None = None,
    ) -> list | dict:
        """Get workout feedback entries."""
        params: dict[str, Any] = {"limit": limit}
        if since:
            params["since"] = since
        if action:
            params["action"] = action
        return await self._request("GET", "/api/workouts/feedback", params=params)

    async def get_missed_workouts(self) -> list | dict:
        """Get past-due incomplete workouts without feedback."""
        # Fetch inventory and feedback, compute the difference
        inventory = await self._request("GET", "/api/workouts/inventory")
        feedback = await self._request("GET", "/api/workouts/feedback", params={"limit": 100})

        from datetime import date, datetime

        today = date.today()
        feedback_workout_ids = set()
        if isinstance(feedback, list):
            for f in feedback:
                wid = f.get("workoutId") or f.get("workout_id")
                if wid:
                    feedback_workout_ids.add(str(wid))

        missed = []
        if isinstance(inventory, list):
            for item in inventory:
                if item.get("complete"):
                    continue
                y, m, d = item.get("year"), item.get("month"), item.get("day")
                if not all(v is not None for v in (y, m, d)):
                    continue
                scheduled = date(y, m, d)
                if scheduled >= today:
                    continue
                wid = str(item.get("id", ""))
                if wid in feedback_workout_ids:
                    continue
                missed.append({
                    "workoutId": wid,
                    "displayName": item.get("display_name", ""),
                    "scheduledDate": scheduled.isoformat(),
                    "daysMissed": (today - scheduled).days,
                })

        return missed

    async def create_actions_batch(self, actions: list[dict]) -> list | dict:
        """Create multiple workout actions in one request."""
        return await self._request("POST", "/api/workouts/actions/batch", json=actions)

    async def create_queue_items_batch(self, items: list[dict]) -> list | dict:
        """Create multiple queue items in one request."""
        return await self._request("POST", "/api/queue/batch", json=items)

    async def create_plan(self, plan: dict) -> list | dict:
        """Create a training plan."""
        return await self._request("POST", "/api/plans", json=plan)

    async def list_plans(
        self,
        status: str | None = None,
        activity_type: str | None = None,
    ) -> list | dict:
        """List training plans."""
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        if activity_type:
            params["activity_type"] = activity_type
        return await self._request("GET", "/api/plans", params=params)

    async def get_plan(self, plan_id: str) -> list | dict:
        """Get a single plan by ID."""
        return await self._request("GET", f"/api/plans/{plan_id}")

    async def update_plan(self, plan_id: str, updates: dict) -> list | dict:
        """Update a plan."""
        return await self._request("PATCH", f"/api/plans/{plan_id}", json=updates)

    async def get_plan_workouts(self, plan_id: str) -> list | dict:
        """Get all queued workouts for a plan."""
        return await self._request("GET", f"/api/plans/{plan_id}/workouts")

    async def get_plan_schedule(self, plan_id: str) -> list | dict:
        """Get a plan's recurring schedule, resolved to dates with conflicts."""
        return await self._request("GET", f"/api/plans/{plan_id}/schedule")

    async def set_plan_schedule(self, plan_id: str, schedule: dict) -> list | dict:
        """Set (replace) a plan's recurring weekly schedule."""
        return await self._request("PUT", f"/api/plans/{plan_id}/schedule", json=schedule)

    async def clear_plan_schedule(self, plan_id: str) -> list | dict:
        """Remove a plan's recurring schedule."""
        return await self._request("DELETE", f"/api/plans/{plan_id}/schedule")

    async def get_training_calendar(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list | dict:
        """Get the unified run + strength calendar over a date window."""
        params: dict[str, Any] = {}
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        return await self._request("GET", "/api/schedule/calendar", params=params)

    async def get_plan_context(
        self,
        plan_id: str | None = None,
        since_days: int = 60,
        limit: int = 40,
    ) -> list | dict:
        """Get the aggregated plan-continuity payload for an LLM conversation."""
        params: dict[str, Any] = {"since_days": since_days, "limit": limit}
        if plan_id:
            params["plan_id"] = plan_id
        return await self._request("GET", "/api/plan-notes/context", params=params)

    async def list_plan_notes(
        self,
        plan_id: str | None = None,
        kind: str | None = None,
        conversation_id: str | None = None,
        since_days: int | None = None,
        include_expired: bool = False,
        limit: int = 50,
    ) -> list | dict:
        """List plan notes with optional filters."""
        params: dict[str, Any] = {"limit": limit, "include_expired": include_expired}
        if plan_id:
            params["plan_id"] = plan_id
        if kind:
            params["kind"] = kind
        if conversation_id:
            params["conversation_id"] = conversation_id
        if since_days is not None:
            params["since_days"] = since_days
        return await self._request("GET", "/api/plan-notes", params=params)

    async def create_plan_note(self, note: dict) -> list | dict:
        """Create a plan note."""
        return await self._request("POST", "/api/plan-notes", json=note)

    async def update_plan_note(self, note_id: str, updates: dict) -> list | dict:
        """Update a plan note."""
        return await self._request("PATCH", f"/api/plan-notes/{note_id}", json=updates)

    async def delete_plan_note(self, note_id: str) -> dict:
        """Delete a plan note."""
        self._ensure_configured()
        url = f"{self.base_url}/api/plan-notes/{note_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as http_client:
            response = await http_client.request("DELETE", url, headers=self.headers)
            if response.status_code == 404:
                raise ValueError(f"Note not found: {note_id}")
            response.raise_for_status()
            return {"deleted": note_id}

    async def get_health_metrics(
        self,
        start_date: str,
        end_date: str | None = None,
    ) -> list | dict:
        """Get daily health metrics for a date range."""
        params: dict[str, Any] = {"start_date": start_date}
        if end_date:
            params["end_date"] = end_date
        return await self._request("GET", "/api/health/metrics", params=params)


# Singleton instance
client = TrainingClient()
