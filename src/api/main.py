import time
import uuid
import logging
from fastapi import FastAPI, Request, Response
from src.api.routes import admin, ask, auth, conversations, documents, search

# 1. Configuration des logs structurés
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_api")

app = FastAPI(
    title="Regulatory Assistant API",
    version="0.1.0",
)

# 2. Middleware de traçabilité (Request ID, latence, logs)
@app.middleware("http")
async def add_traceability_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    start_time = time.time()
    
    request.state.request_id = request_id
    
    try:
        response: Response = await call_next(request)
        process_time = (time.time() - start_time) * 1000
        
        logger.info(
            f"method={request.method} path={request.url.path} "
            f"status_code={response.status_code} request_id={request_id} "
            f"latency_ms={process_time:.2f}"
        )
        
        response.headers["X-Request-ID"] = request_id
        return response
        
    except Exception as e:
        process_time = (time.time() - start_time) * 1000
        logger.error(
            f"method={request.method} path={request.url.path} "
            f"error={str(e)} request_id={request_id} latency_ms={process_time:.2f}"
        )
        raise e

# 3. Montage propre des routeurs (sans doublons)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(ask.router, prefix="/ask", tags=["ask"])

@app.get("/health")
def health_check():
    return {"status": "ok"}