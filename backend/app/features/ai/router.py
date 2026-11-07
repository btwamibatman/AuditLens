from fastapi import APIRouter

from app.features.ai import service
from app.features.ai.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    return service.chat(request)
