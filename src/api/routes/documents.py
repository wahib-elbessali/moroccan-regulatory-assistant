from fastapi import APIRouter

router = APIRouter(prefix="/documents", tags=["documents"])

@router.post("")
def upload_document():
    return {"message": "fake upload endpoint"}

@router.get("")
def list_documents():
    return []

@router.get("/{doc_id}/status")
def get_document_status(doc_id: str):
    return {"doc_id": doc_id, "status": "received"}

@router.delete("/{doc_id}")
def delete_document(doc_id: str):
    return {"message": "deleted"}