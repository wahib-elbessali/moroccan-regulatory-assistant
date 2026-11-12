from fastapi import APIRouter

router = APIRouter()


@router.post("/login")
def login():
    return {"message": "login endpoint"}


@router.get("/me")
def get_me():
    return {"message": "user data"}


@router.post("/account-requests")
def create_account_request():
    return {"status": "pending"}
