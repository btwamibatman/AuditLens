from fastapi import APIRouter, File, UploadFile, status

from app.features.uploads import service
from app.features.uploads.service import UploadRead

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", response_model=UploadRead, status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile = File(...)):
    return await service.save_upload(file)


@router.get("", response_model=list[UploadRead])
def list_files():
    return service.list_uploads()
