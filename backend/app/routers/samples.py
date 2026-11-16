from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services import sample_service as svc

router = APIRouter(tags=["samples"])


class SampleRunBody(BaseModel):
    subject_id: int
    rate: float | None = Field(default=None, ge=0, le=1)
    seed: str = "核证匣-默认种子"


@router.get("/samples")
def list_samples():
    return svc.list_batches()


@router.get("/samples/{batch_id}")
def get_sample(batch_id: int):
    return svc.get_batch(batch_id)


@router.post("/samples/run")
def run_sample(body: SampleRunBody) -> dict[str, Any]:
    return svc.run_sample(body.subject_id, rate=body.rate, seed=body.seed)
