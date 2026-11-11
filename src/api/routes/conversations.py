from fastapi import APIRouter

router = APIRouter()

@router.get("")
@router.get("/")
def list_conversations():
    return []

@router.post("")
@router.post("/")
def create_conversation():
    return {"id": "conv_123"}

@router.get("/{conversation_id}")
def get_conversation(conversation_id: str):
    return {"id": conversation_id}

@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str):
    return {"id": conversation_id, "status": "deleted"}

@router.post("/{conversation_id}/messages")
def add_message(conversation_id: str):
    return {"conversation_id": conversation_id, "status": "message_added"}