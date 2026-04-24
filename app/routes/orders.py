import logging
from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import get_current_user, get_product_details
from app.models import (
    CreateOrderRequest,
    OrderResponse,
    OrderStatus,
    UpdateOrderStatusRequest,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def serialize_order(order: dict) -> dict:
    """Convert MongoDB document to serializable dict."""
    order["id"] = str(order.pop("_id"))
    return order


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_data: CreateOrderRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Create a new order after validating products."""
    db = request.app.state.db

    # Fetch product details for each item
    order_items = []
    total_amount = 0.0

    for item in order_data.items:
        product = await get_product_details(item.product_id)

        if product.get("stock", 0) < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for product '{product['name']}'"
            )

        subtotal = round(product["price"] * item.quantity, 2)
        total_amount += subtotal

        order_items.append({
            "product_id": item.product_id,
            "product_name": product["name"],
            "product_price": product["price"],
            "quantity": item.quantity,
            "subtotal": subtotal
        })

    now = datetime.now(timezone.utc)
    order_doc = {
        "user_id": current_user["userId"],
        "user_email": current_user["email"],
        "items": order_items,
        "total_amount": round(total_amount, 2),
        "shipping_address": order_data.shipping_address,
        "status": OrderStatus.PENDING,
        "created_at": now,
        "updated_at": now
    }

    result = await db.orders.insert_one(order_doc)
    created_order = await db.orders.find_one({"_id": result.inserted_id})

    logger.info(f"Order created: {result.inserted_id} for user {current_user['email']}")
    return serialize_order(created_order)


@router.get("/", response_model=List[OrderResponse])
async def get_my_orders(
    request: Request,
    current_user: dict = Depends(get_current_user),
    status_filter: Optional[str] = None
):
    """Get all orders for the current user."""
    db = request.app.state.db

    query = {"user_id": current_user["userId"]}
    if status_filter:
        query["status"] = status_filter

    cursor = db.orders.find(query).sort("created_at", -1)
    orders = []
    async for order in cursor:
        orders.append(serialize_order(order))

    return orders


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Get a specific order by ID."""
    db = request.app.state.db

    if not ObjectId.is_valid(order_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid order ID"
        )

    order = await db.orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    # Users can only see their own orders
    if order["user_id"] != current_user["userId"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    return serialize_order(order)


@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: str,
    status_update: UpdateOrderStatusRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Update order status (owner or admin)."""
    db = request.app.state.db

    if not ObjectId.is_valid(order_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid order ID"
        )

    order = await db.orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    if order["user_id"] != current_user["userId"] and current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Only allow cancellation by non-admins
    if current_user.get("role") != "admin" and status_update.status != OrderStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Users can only cancel their own orders"
        )

    updated = await db.orders.find_one_and_update(
        {"_id": ObjectId(order_id)},
        {"$set": {"status": status_update.status, "updated_at": datetime.now(timezone.utc)}},
        return_document=True
    )

    logger.info(f"Order {order_id} status updated to {status_update.status}")
    return serialize_order(updated)
