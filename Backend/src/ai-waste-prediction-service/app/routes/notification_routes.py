from fastapi import APIRouter
from app.controllers import notification_controller

router = APIRouter()

@router.get("")
@router.get("/")
async def get_all_notifications():
    return await notification_controller.get_all_notifications()

@router.get("/{batch_id}")
async def get_notifications_by_batch_id(batch_id: str):
    return await notification_controller.get_notifications_by_batch_id(batch_id)