from fastapi import APIRouter

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
def list_conversations():
    return []


@router.post("")
def create_conversation():
    return {"message": "conversation created"}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str):
    return {"conversation_id": conversation_id, "messages": []}


@router.post("/{conversation_id}/messages")
def add_message(conversation_id: str):
    return {"message": "message added"}


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str):
    return {"message": "conversation deleted"}
