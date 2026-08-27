"""
StyleHub Common Pydantic Data Models
Clean, standard Python data structures for microservice REST APIs
"""

from pydantic import BaseModel
from typing import List, Optional

class Money(BaseModel):
    currency_code: str = "USD"
    units: int
    nanos: int = 0

class CartItem(BaseModel):
    product_id: str
    quantity: int

class AddItemRequest(BaseModel):
    user_id: str
    item: CartItem

class UpdateQuantityRequest(BaseModel):
    user_id: str
    product_id: str
    quantity: int

class Address(BaseModel):
    street_address: str
    city: str
    state: str
    country: str = "United States"
    zip_code: int

class CreditCardInfo(BaseModel):
    credit_card_number: str
    credit_card_cvv: int
    credit_card_expiration_year: int
    credit_card_expiration_month: int

class PlaceOrderRequest(BaseModel):
    user_id: str
    user_currency: str = "USD"
    email: str
    address: Address
    credit_card: CreditCardInfo
