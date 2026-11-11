from fastapi import APIRouter

router = APIRouter(prefix="/ask", tags=["ask (P3)"])


@router.post("")
def ask_question():
    return {"answer": "fake answer"}
