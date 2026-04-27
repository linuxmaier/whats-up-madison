from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.routers import events

Base.metadata.create_all(bind=engine)

app = FastAPI(title="What's Up Madison")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(events.router)


@app.get("/health")
def health():
    return {"status": "ok"}
