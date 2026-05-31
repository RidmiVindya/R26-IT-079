from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.batch_routes import router as batch_router
from app.routes.notification_routes import router as notification_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(batch_router, prefix="/api/batches")
app.include_router(notification_router, prefix="/api/notifications")

@app.get("/")
async def home():
    return {"message": "Python backend running successfully"}