from fastapi import APIRouter

router = APIRouter()


@router.get("/users")
def list_users():
    return []


@router.post("/users")
def create_user():
    return {"status": "created"}


@router.patch("/users/{user_id}/role")
def update_user_role(user_id: str):
    return {"status": "updated"}


@router.patch("/users/{user_id}/active")
def update_user_active(user_id: str):
    return {"status": "updated"}


@router.get("/roles")
def list_roles():
    return []


@router.patch("/roles/{role_id}/web")
def update_role_web(role_id: str):
    return {"status": "updated"}


@router.put("/documents/{doc_id}/roles")
def update_doc_roles(doc_id: str):
    return {"status": "updated"}


@router.get("/audit")
def get_audit():
    return []


@router.get("/account-requests")
def list_account_requests():
    return []


@router.post("/account-requests/{request_id}/approve")
def approve_request(request_id: str):
    return {"status": "approved"}


@router.post("/account-requests/{request_id}/reject")
def reject_request(request_id: str):
    return {"status": "rejected"}
