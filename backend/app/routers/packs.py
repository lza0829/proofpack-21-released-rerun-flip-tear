from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import pack_service as svc

router = APIRouter(tags=["packs"])


class BuildPackBody(BaseModel):
    batch_id: int


@router.get("/packs")
def list_packs():
    return svc.list_packs()


@router.get("/packs/{pack_id}")
def get_pack(pack_id: int):
    return svc.get_pack(pack_id)


@router.post("/packs/build")
def build_pack(body: BuildPackBody) -> dict[str, Any]:
    return svc.build_pack(body.batch_id)
