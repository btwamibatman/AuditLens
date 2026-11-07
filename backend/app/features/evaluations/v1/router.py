from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.features.evaluations.v1.provider import OpenAIProvider, ProviderSettings
from app.features.evaluations.v1.service import error_result, evaluate

router = APIRouter(prefix="/v1/evaluations", tags=["evaluations v1"])


@router.post("")
async def evaluate_conversation(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(error_result("", "Invalid request JSON"), status_code=400)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("conversation_id"), str)
        or not payload["conversation_id"].strip()
    ):
        return JSONResponse(error_result("", "conversation_id is required"), status_code=400)
    from starlette.concurrency import run_in_threadpool

    result, status = await run_in_threadpool(
        evaluate, payload["conversation_id"], OpenAIProvider(ProviderSettings())
    )
    return JSONResponse(result, status_code=status)
