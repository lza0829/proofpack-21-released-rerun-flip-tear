from fastapi import APIRouter

from app.services import consistency_service
from app.services import sample_service as svc

router = APIRouter(tags=["dashboard"])


@router.get("/health")
def health():
    return {"ok": True, "project": "proofpack", "name": "核证匣"}


@router.get("/dashboard")
def dashboard():
    return svc.dashboard_stats()


@router.get("/consistency")
def consistency():
    return consistency_service.audit()
