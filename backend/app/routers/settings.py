from fastapi import APIRouter
from pydantic import BaseModel

from app.services import release_service as svc

router = APIRouter(tags=["settings"])


class PolicyBody(BaseModel):
    release_run_policy: str


@router.get("/settings")
def list_settings():
    return svc.list_settings()


@router.post("/settings/release-policy")
def set_release_policy(body: PolicyBody):
    return svc.set_release_policy(body.release_run_policy)
