from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
import hashlib
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders, tasks

app = FastAPI(title="Factory Inventory Management System")

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    location: str
    last_updated: str

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False
    # Dashboard switches the row action between "Create PO" and "View PO" on this
    # field, so it has to survive a page reload — not just the in-session emit.
    purchase_order_id: Optional[str] = None

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    notes: Optional[str] = None

class EnrichedDemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str
    # Restocking-specific fields resolved server-side (see /api/demand/enriched)
    unit_cost: float
    cost_source: str  # "sku" | "name" | "synthesized" — lets UI/tests see how price was derived
    lead_time_days: int

class Task(BaseModel):
    id: str
    title: str
    priority: str
    # camelCase to match the shape TasksModal.vue already renders for mock tasks
    dueDate: str
    status: str

class CreateTaskRequest(BaseModel):
    title: str
    priority: str = "medium"
    dueDate: str

class RestockingOrderItem(BaseModel):
    sku: str
    name: str
    quantity: int
    unit_price: float
    lead_time_days: Optional[int] = None

class RestockingOrderRequest(BaseModel):
    items: List[RestockingOrderItem]
    budget: Optional[float] = None  # recorded for reference only; recommendation math happens client-side

# Restocking helpers
# Demand forecast items carry no cost, and their SKUs mostly don't match inventory
# (only 1 of 9 by SKU, 2 by name). For the 7 unmatched items we synthesize a
# deterministic price from a hash of the SKU so recommendations stay stable across
# restarts and land inside the real inventory cost range ($6.50–$725).
def _synth_cost(sku: str) -> float:
    h = int(hashlib.md5(sku.encode()).hexdigest(), 16)
    return round(10 + (h % 491) + (h % 100) / 100, 2)  # $10.00–$500.99

# Deterministic per-item lead time (7–21 days) so the value shown pre-order matches
# the value stored on the submitted order.
def _lead_time_days(sku: str) -> int:
    return 7 + (int(hashlib.md5(sku.encode()).hexdigest(), 16) % 15)

def _resolve_unit_cost(forecast: dict) -> tuple:
    """Resolve a forecast item's unit cost. Returns (unit_cost, source)."""
    sku = forecast.get("item_sku", "")
    # 1. exact SKU match against inventory (case-insensitive)
    match = next((i for i in inventory_items if i.get("sku", "").strip().upper() == sku.strip().upper()), None)
    if match:
        return match["unit_cost"], "sku"
    # 2. fall back to name match (covers items whose SKU differs but name is identical)
    name = forecast.get("item_name", "")
    match = next((i for i in inventory_items if i.get("name", "").strip().lower() == name.strip().lower()), None)
    if match:
        return match["unit_cost"], "name"
    # 3. no inventory match — synthesize a stable, plausible price
    return _synth_cost(sku), "synthesized"

# API endpoints
@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.get("/api/demand/enriched", response_model=List[EnrichedDemandForecast])
def get_enriched_demand_forecasts():
    """Get demand forecasts enriched with a resolved unit_cost and lead time for restocking."""
    enriched = []
    for f in demand_forecasts:
        unit_cost, source = _resolve_unit_cost(f)
        enriched.append({
            **f,
            "unit_cost": unit_cost,
            "cost_source": source,
            "lead_time_days": _lead_time_days(f.get("item_sku", "")),
        })
    return enriched

@app.post("/api/restocking/orders", response_model=Order, status_code=201)
def create_restocking_order(request: RestockingOrderRequest):
    """Create a restocking order from selected forecast items and append it to the orders list."""
    if not request.items:
        raise HTTPException(status_code=400, detail="At least one item is required")

    # Generate the next numeric id. The isdigit() guard avoids a crash if a
    # non-numeric id ever ends up in the list (all seed ids are "1".."250").
    next_id = max((int(o["id"]) for o in orders if str(o.get("id", "")).isdigit()), default=250) + 1

    order_date = datetime.now().date()
    # Order isn't complete until the slowest item arrives, so lead time = max of the items'.
    max_lead = max((item.lead_time_days or 0) for item in request.items)
    expected_delivery = order_date + timedelta(days=max_lead)

    new_order = {
        "id": str(next_id),
        # Year derives from the order date so the sequence reads ORD-2026-0251, not the seed's 2025.
        "order_number": f"ORD-{order_date.year}-{next_id:04d}",
        "customer": "Internal Restock",
        "items": [
            {"sku": i.sku, "name": i.name, "quantity": i.quantity, "unit_price": i.unit_price}
            for i in request.items
        ],
        "status": "Submitted",
        "order_date": order_date.isoformat(),
        "expected_delivery": expected_delivery.isoformat(),
        "total_value": round(sum(i.quantity * i.unit_price for i in request.items), 2),
        "actual_delivery": None,
        "warehouse": None,
        "category": None,
    }

    # Append to the module-level list: persists across requests within the running
    # process (lost on restart — acceptable for this demo, no database).
    orders.append(new_order)
    return new_order

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    # Add has_purchase_order flag to each backlog item
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        # Check if this backlog item has a purchase order
        po = next((po for po in purchase_orders if po["backlog_item_id"] == item["id"]), None)
        item_dict["has_purchase_order"] = po is not None
        item_dict["purchase_order_id"] = po["id"] if po else None
        result.append(item_dict)
    return result

@app.post("/api/purchase-orders", response_model=PurchaseOrder, status_code=201)
def create_purchase_order(request: CreatePurchaseOrderRequest):
    """Create a purchase order for a backlog item."""
    backlog_item = next((b for b in backlog_items if b["id"] == request.backlog_item_id), None)
    if not backlog_item:
        raise HTTPException(status_code=404, detail=f"Backlog item {request.backlog_item_id} not found")

    if any(po["backlog_item_id"] == request.backlog_item_id for po in purchase_orders):
        raise HTTPException(
            status_code=400,
            detail=f"Backlog item {request.backlog_item_id} already has a purchase order"
        )

    if request.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")
    if request.unit_cost < 0:
        raise HTTPException(status_code=400, detail="Unit cost cannot be negative")

    new_po = {
        "id": f"PO-{len(purchase_orders) + 1:04d}",
        "backlog_item_id": request.backlog_item_id,
        "supplier_name": request.supplier_name,
        "quantity": request.quantity,
        "unit_cost": request.unit_cost,
        "expected_delivery_date": request.expected_delivery_date,
        "status": "pending",
        "created_date": datetime.now().strftime("%Y-%m-%d"),
        "notes": request.notes
    }
    purchase_orders.append(new_po)
    return new_po

@app.get("/api/purchase-orders/{backlog_item_id}", response_model=PurchaseOrder)
def get_purchase_order_by_backlog_item(backlog_item_id: str):
    """Get the purchase order raised against a backlog item."""
    po = next((po for po in purchase_orders if po["backlog_item_id"] == backlog_item_id), None)
    if not po:
        raise HTTPException(
            status_code=404,
            detail=f"No purchase order found for backlog item {backlog_item_id}"
        )
    return po

@app.get("/api/tasks", response_model=List[Task])
def get_tasks():
    """Get all runtime-created tasks (newest first, matching the modal's order)."""
    return list(reversed(tasks))

@app.post("/api/tasks", response_model=Task, status_code=201)
def create_task(request: CreateTaskRequest):
    """Create a task."""
    if not request.title.strip():
        raise HTTPException(status_code=400, detail="Task title cannot be empty")
    if request.priority not in ("high", "medium", "low"):
        raise HTTPException(status_code=400, detail="Priority must be high, medium or low")

    new_task = {
        # Counter-based ids would collide after a delete, so key off the highest
        # existing id instead.
        "id": f"TASK-{max((int(t['id'].split('-')[-1]) for t in tasks), default=0) + 1:04d}",
        "title": request.title.strip(),
        "priority": request.priority,
        "dueDate": request.dueDate,
        "status": "pending"
    }
    tasks.append(new_task)
    return new_task

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str):
    """Delete a task."""
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    tasks.remove(task)
    return {"deleted": task_id}

@app.patch("/api/tasks/{task_id}", response_model=Task)
def toggle_task(task_id: str):
    """Toggle a task between pending and completed."""
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    task["status"] = "pending" if task["status"] == "completed" else "completed"
    return task

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/reports/quarterly")
def get_quarterly_reports():
    """Get quarterly performance reports"""
    # Calculate quarterly statistics from orders
    quarters = {}

    for order in orders:
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends():
    """Get month-over-month trends"""
    months = {}

    for order in orders:
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
