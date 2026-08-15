from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.auth_router import router as auth_router

app = FastAPI(
    title="Smart Karawala Authentication API"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Development only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

@app.get("/")
def root():
    return {"message": "Authentication API Running"}


if __name__ == "__main__":
    import os
    import uvicorn

    # Dedicated auth port so it doesn't clash with batch (8000), time/spoilage
    # (8001) or IoT (8002).
    port = int(os.getenv("PORT", 8003))
    host = os.getenv("HOST", "0.0.0.0")

    uvicorn.run("app.main:app", host=host, port=port, reload=True)