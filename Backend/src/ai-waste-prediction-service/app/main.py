from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.batch_routes import router as batch_router
from app.routes.notification_routes import router as notification_router
from app.routes.company_routes import router as company_router
from app.routes.dashboard_routes import router as dashboard_router
from app.routes.salting_routes import router as salting_router
    
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
app.include_router(company_router, prefix="/api/companies")
app.include_router(dashboard_router, prefix="/api/dashboard")
app.include_router(salting_router, prefix="/api/salting")


@app.get("/")
async def home():
    return {"message": "Python backend running successfully"}