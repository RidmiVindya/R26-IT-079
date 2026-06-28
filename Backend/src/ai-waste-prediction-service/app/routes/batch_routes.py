from fastapi import APIRouter, Body
from app.controllers import batch_controller

router = APIRouter()

@router.post("/")
async def create_batch(data: dict = Body(...)):
    return await batch_controller.create_batch(data)

@router.get("/")
async def get_all_batches():
    return await batch_controller.get_all_batches()

@router.get("/{batch_id}")
async def get_batch_by_id(batch_id: str):
    return await batch_controller.get_batch_by_id(batch_id)

@router.put("/{batch_id}")
async def update_batch(batch_id: str, data: dict = Body(...)):
    return await batch_controller.update_batch(batch_id, data)

@router.delete("/{batch_id}")
async def delete_batch(batch_id: str):
    return await batch_controller.delete_batch(batch_id)

@router.post("/{batch_id}/predict-waste")
async def predict_waste(batch_id: str):
    return await batch_controller.predict_waste(batch_id)

@router.post("/{batch_id}/predict-salt")
async def predict_salt(batch_id: str):
    return await batch_controller.predict_salt(batch_id)

@router.post("/{batch_id}/start-salting")
async def start_salting(batch_id: str):
    return await batch_controller.start_salting(batch_id)

@router.get("/{batch_id}/monitoring")
async def get_monitoring(batch_id: str):
    return await batch_controller.get_monitoring(batch_id)

@router.post("/{batch_id}/send-waste-notification")
async def send_waste_notification(batch_id: str):
    return await batch_controller.send_waste_notification(batch_id)


    