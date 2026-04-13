from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"service": "options-screener", "status": "healthy"}
