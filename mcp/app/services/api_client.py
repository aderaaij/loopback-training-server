"""HTTP client for Training API."""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TrainingClient:
    """Client for interacting with Training REST API."""

    def __init__(self) -> None:
        self.base_url = settings.training_api_url.rstrip("/")
        self.timeout = settings.request_timeout
        self._api_key = settings.training_api_key.get_secret_value()

    def _ensure_configured(self) -> None:
        """Raise an error if the API key is not configured."""
        if not self._api_key:
            from app.config import Settings

            env_file = Settings.model_config.get("env_file")
            raise ValueError(f"TRAINING_API_KEY is not configured. Please set it in: {env_file}")

    @property
    def headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> list | dict:
        """Make an HTTP request to the Training API."""
        self._ensure_configured()
        url = f"{self.base_url}{path}"
        logger.debug(f"Making {method} request to {url}")

        async with httpx.AsyncClient(timeout=self.timeout) as http_client:
            response = await http_client.request(
                method=method,
                url=url,
                headers=self.headers,
                **kwargs,
            )

            if response.status_code == 401:
                raise ValueError("Invalid API key. Check your TRAINING_API_KEY configuration.")
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
        return await self._request("POST", "/api/queue", json=body)

    async def update_queue_item(self, item_id: str, **fields: Any) -> list | dict:
        """Update a queue item's fields."""
        body: dict[str, Any] = {}
        key_map = {
            "activity_type": "activityType",
            "title": "title",
            "description": "description",
            "workout_data": "workoutData",
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


# Singleton instance
client = TrainingClient()
