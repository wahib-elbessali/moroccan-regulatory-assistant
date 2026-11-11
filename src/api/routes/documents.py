from fastapi import APIRouter

router = APIRouter()

@router.get("")
@router.get("/")
def list_documents():
    return []

@router.post("")
@router.post("/")
def upload_document():
    return {"status": "uploaded"}

@router.get("/{doc_id}/status")
def get_document_status(doc_id: str):
    return {"doc_id": doc_id, "status": "processed"}

@router.delete("/{doc_id}")
def delete_document(doc_id: str):
    return {"doc_id": doc_id, "status": "deleted"}