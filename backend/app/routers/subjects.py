from fastapi import APIRouter

from app.services import sample_service as svc

router = APIRouter(tags=["subjects"])


@router.get("/subjects")
def list_subjects():
    return svc.list_subjects()


@router.get("/subjects/{subject_id}")
def get_subject(subject_id: int):
    return svc.get_subject(subject_id)
