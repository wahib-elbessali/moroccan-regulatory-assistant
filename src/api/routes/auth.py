from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login")
def login():
    return {"message": "fake login endpoint"}

@router.get("/me")
def get_me():
    return {"message": "fake me endpoint"}

@router.post("/logout")
def logout():
    return {"message": "fake logout endpoint"}