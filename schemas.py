"""
Inventory Management Schemas

Each Pydantic model maps to a MongoDB collection. Collection name is the lowercase of the class name.
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime

# Auth / User
class User(BaseModel):
    login_id: str = Field(..., description="Unique login identifier")
    email: EmailStr
    password_hash: str = Field(..., description="Hashed password")
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: Literal['admin','user'] = 'user'
    is_active: bool = True

# Master data
class Warehouse(BaseModel):
    name: str
    code: str = Field(..., description="Short code")
    address: Optional[str] = None

class Location(BaseModel):
    name: str
    code: str
    warehouse_code: str

class Product(BaseModel):
    sku: str = Field(..., description="Unique product code e.g. DESK001")
    name: str
    cost: float = 0
    on_hand: int = 0
    free_to_use: int = 0

# Operations
ReceiptStatus = Literal['Draft','Ready','Done','Canceled']
DeliveryStatus = Literal['Draft','Waiting','Ready','Done','Canceled']

class ReceiptLine(BaseModel):
    product_sku: str
    quantity: int = Field(ge=0)

class DeliveryLine(BaseModel):
    product_sku: str
    quantity: int = Field(ge=0)

class Receipt(BaseModel):
    reference: str
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    contact: Optional[str] = None
    schedule_date: Optional[datetime] = None
    status: ReceiptStatus = 'Draft'
    responsible: Optional[str] = None
    lines: List[ReceiptLine] = []

class Delivery(BaseModel):
    reference: str
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    contact: Optional[str] = None
    schedule_date: Optional[datetime] = None
    status: DeliveryStatus = 'Draft'
    responsible: Optional[str] = None
    operation_type: Literal['Customer Delivery','Internal Transfer','Return'] = 'Customer Delivery'
    lines: List[DeliveryLine] = []

class Move(BaseModel):
    reference: str
    date: datetime
    contact: Optional[str] = None
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    product_sku: str
    quantity: int
    direction: Literal['in','out']
    status: Literal['Draft','Done'] = 'Draft'
