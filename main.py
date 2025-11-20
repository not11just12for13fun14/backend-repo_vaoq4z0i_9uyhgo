import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from database import db, create_document, get_documents

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class LoginResponse(BaseModel):
    token: str
    email: EmailStr
    name: str
    coins: int


class AddCoinsRequest(BaseModel):
    amount: int


# Helpers

def _get_user_by_email(email: str) -> Optional[dict]:
    doc = db["usercoin"].find_one({"email": email})
    return doc


def _get_user_by_id(user_id: str) -> Optional[dict]:
    from bson.objectid import ObjectId
    try:
        oid = ObjectId(user_id)
    except Exception:
        return None
    return db["usercoin"].find_one({"_id": oid})


def _create_or_get_session(user: dict) -> str:
    existing = db["session"].find_one({"user_id": str(user["_id"])})
    if existing:
        return existing.get("token")
    token = secrets.token_hex(24)
    create_document("session", {"token": token, "user_id": str(user["_id"]), "user_email": user["email"]})
    return token


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.replace("Bearer ", "").strip()
    sess = db["session"].find_one({"token": token})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = _get_user_by_id(sess["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found for token")
    return user


@app.get("/")
def read_root():
    return {"message": "AV Coins Backend Running"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"

            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    # Check environment variables
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    user = _get_user_by_email(payload.email)
    if not user:
        name = payload.name or payload.email.split("@")[0]
        create_document("usercoin", {"email": payload.email, "name": name, "coins": 0})
        user = _get_user_by_email(payload.email)

    if payload.name and payload.name != user.get("name"):
        db["usercoin"].update_one({"_id": user["_id"]}, {"$set": {"name": payload.name, "updated_at": datetime.now(timezone.utc)}})
        user = _get_user_by_email(payload.email)

    token = _create_or_get_session(user)

    return LoginResponse(token=token, email=user["email"], name=user.get("name", ""), coins=int(user.get("coins", 0)))


@app.get("/me", response_model=LoginResponse)
def me(user: dict = Depends(get_current_user), authorization: Optional[str] = Header(None)):
    token = authorization.replace("Bearer ", "").strip() if authorization else ""
    return LoginResponse(token=token, email=user["email"], name=user.get("name", ""), coins=int(user.get("coins", 0)))


@app.post("/coins/add")
def add_coins(payload: AddCoinsRequest, user: dict = Depends(get_current_user)):
    amt = int(payload.amount)
    if amt == 0:
        return {"coins": int(user.get("coins", 0))}
    if abs(amt) > 10000:
        raise HTTPException(status_code=400, detail="Amount too large")
    new_total = int(user.get("coins", 0)) + amt
    if new_total < 0:
        new_total = 0
    db["usercoin"].update_one({"_id": user["_id"]}, {"$set": {"coins": new_total, "updated_at": datetime.now(timezone.utc)}})
    return {"coins": new_total}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
