from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import release_service as svc

router = APIRouter(tags=["releases"])


class ReleaseBody(BaseModel):
    pack_id: int
    decision: str
    reason: str | None = None
    run_id: int | None = None
    run_no: str | None = None


@router.get("/releases")
def list_releases():
    return svc.list_releases()


@router.post("/releases/decide")
def decide(body: ReleaseBody) -> dict[str, Any]:
    return svc.decide(
        body.pack_id,
        body.decision,
        body.reason,
        run_id=body.run_id,
        run_no=body.run_no,
    )
