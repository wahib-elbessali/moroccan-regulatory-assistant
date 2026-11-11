from fastapi import APIRouter

router = APIRouter()


@router.post("")
@router.post("/")
def ask_question():
    return {"answer": "regulatory response"}
