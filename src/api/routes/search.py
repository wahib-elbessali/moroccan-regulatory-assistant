from fastapi import APIRouter

router = APIRouter(prefix="/search", tags=["search (P2)"])


@router.post("")
def search():
    return {"results": []}
