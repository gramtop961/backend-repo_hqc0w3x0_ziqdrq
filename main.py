import os
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User, Product, Warehouse, Location, Receipt, Delivery, Move

app = FastAPI(title="Inventory Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utility
class IdModel(BaseModel):
    id: str

def obj_to_dict(obj):
    if isinstance(obj, dict):
        d = obj.copy()
        if d.get("_id"):
            d["id"] = str(d.pop("_id"))
        return d
    return obj

@app.get("/")
def read_root():
    return {"message": "Inventory Backend Running"}

# Seed data for demo experience
@app.post("/seed")
def seed():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # Simple idempotent seeds
    def upsert(col, filt, doc):
        existing = db[col].find_one(filt)
        if existing:
            return str(existing["_id"])
        return create_document(col, doc)

    upsert("warehouse", {"code": "WH"}, Warehouse(name="Main Warehouse", code="WH", address="HQ").model_dump())
    upsert("location", {"code": "STOCK"}, Location(name="Stock", code="STOCK", warehouse_code="WH").model_dump())
    upsert("location", {"code": "CUSTOMER"}, Location(name="Customer", code="CUSTOMER", warehouse_code="WH").model_dump())

    upsert("product", {"sku": "DESK001"}, Product(sku="DESK001", name="Desk", cost=3000, on_hand=50, free_to_use=45).model_dump())
    upsert("product", {"sku": "TABLE001"}, Product(sku="TABLE001", name="Table", cost=3000, on_hand=50, free_to_use=50).model_dump())

    # Create example operations if none
    if db["receipt"].count_documents({}) == 0:
        create_document("receipt", Receipt(reference="WH/IN/0001", from_location="SUPPLIER", to_location="STOCK", contact="Acme", schedule_date=datetime.utcnow(), status="Ready", responsible="admin", lines=[{"product_sku":"DESK001","quantity":5}]).model_dump())
    if db["delivery"].count_documents({}) == 0:
        create_document("delivery", Delivery(reference="WH/OUT/0001", from_location="STOCK", to_location="CUSTOMER", contact="John", schedule_date=datetime.utcnow(), status="Waiting", responsible="admin", lines=[{"product_sku":"DESK001","quantity":6}]).model_dump())

    return {"status": "ok"}

# Auth endpoints (simple demo, no real auth)
class LoginRequest(BaseModel):
    login_id: str
    password: str

@app.post("/auth/login")
def login(payload: LoginRequest):
    # Demo: accept any non-empty credentials, return mock user
    if not payload.login_id or not payload.password:
        raise HTTPException(status_code=400, detail="Missing credentials")
    return {"token": "demo-token", "user": {"login_id": payload.login_id, "name": "Demo User", "avatar_url": "https://i.pravatar.cc/100"}}

class SignupRequest(BaseModel):
    login_id: str
    email: str
    password: str
    confirm_password: str

@app.post("/auth/signup")
def signup(payload: SignupRequest):
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    # For demo, just echo
    return {"message": "Signup successful", "login_id": payload.login_id}

class ForgotPayload(BaseModel):
    email: str
    otp: Optional[str] = None
    new_password: Optional[str] = None
    confirm_password: Optional[str] = None

@app.post("/auth/forgot")
def forgot(payload: ForgotPayload):
    if not payload.otp:
        return {"message": "OTP sent to email"}
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    return {"message": "Password reset successful"}

# Dashboard summary
@app.get("/dashboard")
def dashboard():
    def count_status(col, status):
        return db[col].count_documents({"status": status}) if db else 0
    return {
        "receipt": {
            "to_receive": count_status("receipt", "Ready"),
            "late": 1,
            "operations": db["receipt"].count_documents({}) if db else 0,
        },
        "delivery": {
            "to_deliver": count_status("delivery", "Ready"),
            "late": 1,
            "waiting": count_status("delivery", "Waiting"),
            "operations": db["delivery"].count_documents({}) if db else 0,
        }
    }

# CRUD helpers for collections
@app.get("/products")
def list_products():
    items = [obj_to_dict(x) for x in get_documents("product")]
    return items

class ProductUpdate(BaseModel):
    cost: Optional[float] = None
    on_hand: Optional[int] = None
    free_to_use: Optional[int] = None

@app.patch("/products/{sku}")
def update_product(sku: str, payload: ProductUpdate):
    if db is None:
        raise HTTPException(status_code=500, detail="DB not available")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    db["product"].update_one({"sku": sku}, {"$set": update})
    item = db["product"].find_one({"sku": sku})
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    return obj_to_dict(item)

# Operations: Receipts
@app.get("/receipts")
def receipts():
    return [obj_to_dict(x) for x in get_documents("receipt")]

class ReceiptCreate(BaseModel):
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    contact: Optional[str] = None
    schedule_date: Optional[datetime] = None
    lines: List[dict] = []

@app.post("/receipts")
def create_receipt(payload: ReceiptCreate):
    if db is None: raise HTTPException(status_code=500, detail="DB not available")
    count = db["receipt"].count_documents({}) + 1
    reference = f"WH/IN/{count:04d}"
    rec = Receipt(reference=reference, from_location=payload.from_location, to_location=payload.to_location or "STOCK", contact=payload.contact, schedule_date=payload.schedule_date or datetime.utcnow(), status="Draft", responsible="admin", lines=payload.lines)
    create_document("receipt", rec.model_dump())
    return rec

@app.get("/receipts/{reference}")
def get_receipt(reference: str):
    rec = db["receipt"].find_one({"reference": reference})
    if not rec: raise HTTPException(status_code=404, detail="Not found")
    return obj_to_dict(rec)

class StatusPayload(BaseModel):
    action: str

@app.post("/receipts/{reference}/action")
def receipt_action(reference: str, payload: StatusPayload):
    rec = db["receipt"].find_one({"reference": reference})
    if not rec: raise HTTPException(status_code=404, detail="Not found")
    status = rec.get("status", "Draft")
    if payload.action == "todo" and status == "Draft":
        status = "Ready"
    elif payload.action == "validate" and status == "Ready":
        status = "Done"
        # Apply stock in
        for line in rec.get("lines", []):
            db["product"].update_one({"sku": line["product_sku"]}, {"$inc": {"on_hand": line["quantity"], "free_to_use": line["quantity"]}})
        # Log moves
        for line in rec.get("lines", []):
            mv = Move(reference=reference, date=datetime.utcnow(), contact=rec.get("contact"), from_location=rec.get("from_location"), to_location=rec.get("to_location"), product_sku=line["product_sku"], quantity=line["quantity"], direction='in', status='Done')
            create_document("move", mv.model_dump())
    elif payload.action == "cancel":
        status = "Canceled"
    db["receipt"].update_one({"reference": reference}, {"$set": {"status": status}})
    return {"reference": reference, "status": status}

# Operations: Delivery
@app.get("/deliveries")
def deliveries():
    return [obj_to_dict(x) for x in get_documents("delivery")]

class DeliveryCreate(BaseModel):
    to_location: Optional[str] = None
    contact: Optional[str] = None
    schedule_date: Optional[datetime] = None
    lines: List[dict] = []

@app.post("/deliveries")
def create_delivery(payload: DeliveryCreate):
    if db is None: raise HTTPException(status_code=500, detail="DB not available")
    count = db["delivery"].count_documents({}) + 1
    reference = f"WH/OUT/{count:04d}"
    doc = Delivery(reference=reference, from_location="STOCK", to_location=payload.to_location or "CUSTOMER", contact=payload.contact, schedule_date=payload.schedule_date or datetime.utcnow(), status="Draft", responsible="admin", lines=payload.lines)
    create_document("delivery", doc.model_dump())
    return doc

@app.get("/deliveries/{reference}")
def get_delivery(reference: str):
    rec = db["delivery"].find_one({"reference": reference})
    if not rec: raise HTTPException(status_code=404, detail="Not found")
    return obj_to_dict(rec)

@app.post("/deliveries/{reference}/action")
def delivery_action(reference: str, payload: StatusPayload):
    rec = db["delivery"].find_one({"reference": reference})
    if not rec: raise HTTPException(status_code=404, detail="Not found")
    status = rec.get("status", "Draft")
    if payload.action == "todo" and status == "Draft":
        # Check stock
        insufficient = []
        for line in rec.get("lines", []):
            prod = db["product"].find_one({"sku": line["product_sku"]})
            if not prod or prod.get("free_to_use", 0) < line["quantity"]:
                insufficient.append(line)
        status = "Waiting" if insufficient else "Ready"
    elif payload.action == "validate" and status == "Ready":
        status = "Done"
        # Apply stock out
        for line in rec.get("lines", []):
            db["product"].update_one({"sku": line["product_sku"]}, {"$inc": {"on_hand": -line["quantity"], "free_to_use": -line["quantity"]}})
        # Log moves
        for line in rec.get("lines", []):
            mv = Move(reference=reference, date=datetime.utcnow(), contact=rec.get("contact"), from_location=rec.get("from_location"), to_location=rec.get("to_location"), product_sku=line["product_sku"], quantity=line["quantity"], direction='out', status='Done')
            create_document("move", mv.model_dump())
    elif payload.action == "cancel":
        status = "Canceled"
    db["delivery"].update_one({"reference": reference}, {"$set": {"status": status}})
    return {"reference": reference, "status": status}

# Move history
@app.get("/moves")
def moves():
    return [obj_to_dict(x) for x in get_documents("move")]

# Settings
@app.get("/warehouses")
def warehouses():
    return [obj_to_dict(x) for x in get_documents("warehouse")]

@app.get("/locations")
def locations():
    return [obj_to_dict(x) for x in get_documents("location")]

# Keep original test endpoint to verify DB
@app.get("/test")
def test_database():
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
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
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
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
