"""Runtime settings the SPA needs but can't bake in at build time.

The frontend ships inside the Docker image, so anything a self-hoster wants to
change (today: the route-map tile provider) is served from here instead of a
Vite env var. Behind the normal bearer auth: the map only renders for signed-in
users. camelCase on the wire, like the other identity/config-shaped routes.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app import oauth
from app.config import Settings, get_settings

router = APIRouter()


class MapConfigOut(BaseModel):
    # Leaflet URL template; may carry {s} {z} {x} {y} {r} and a query string.
    tileUrl: str
    attribution: str
    # Only used when tileUrl contains {s}.
    subdomains: str


class RuntimeConfigOut(BaseModel):
    map: MapConfigOut
    # The coach endpoint's public address when it is not simply the address
    # the dashboard was opened at, else null. The two differ on a server
    # whose coach endpoint is public and whose dashboard is not (see
    # app/oauth.py), where an assistant in the cloud needs the public one.
    coachUrl: str | None = None


@router.get("", response_model=RuntimeConfigOut)
def get_runtime_config(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, object]:
    return {
        "map": settings.map_tiles,
        "coachUrl": oauth.coach_url_for_dashboard(oauth.public_origin(request.scope)),
    }
