from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
def list_users():
    return []


@router.get("/roles")
def list_roles():
    return []
