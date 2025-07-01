from fastapi import FastAPI, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import sqlite3


# ============ DATABASE UTILS ==============


DB_PATH = "storeinventorypro-1045-63ce8824/inventory_backend/src/api/inventory.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            sku TEXT UNIQUE NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            change INTEGER NOT NULL,
            old_stock INTEGER NOT NULL,
            new_stock INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            remark TEXT,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


# ================== FASTAPI APP =====================


app = FastAPI(
    title="Inventory Management API",
    description=(
        "API for managing product inventory in a general store. Features CRUD, stock tracking, "
        "search/filter, inventory history, and SQLite DB health check."
    ),
    version="1.0.0",
    openapi_tags=[
        {"name": "Products", "description": "Operations on inventory products"},
        {"name": "Stock", "description": "Stock level update/tracking"},
        {"name": "History", "description": "Inventory changes history"},
        {"name": "Health", "description": "Health check endpoints"},
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== SCHEMA MODELS ====================


class ProductBase(BaseModel):
    name: str = Field(..., description="Name of the product")
    description: Optional[str] = Field("", description="Product description")
    sku: str = Field(..., description="Stock Keeping Unit ID (unique)")
    price: float = Field(..., description="Price of the product", gt=0)


class ProductCreate(ProductBase):
    stock: int = Field(0, description="Initial product stock", ge=0)


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Name of the product")
    description: Optional[str] = Field(None, description="Product description")
    sku: Optional[str] = Field(None, description="SKU")
    price: Optional[float] = Field(None, description="Price", gt=0)
    stock: Optional[int] = Field(None, description="Edit stock", ge=0)


class Product(ProductBase):
    id: int
    stock: int
    created_at: datetime
    updated_at: datetime


class StockChange(BaseModel):
    change: int = Field(
        ..., description="How much to change the stock (positive for add, negative for removal)"
    )
    remark: Optional[str] = Field("", description="Remark about the stock change")


class InventoryHistory(BaseModel):
    id: int
    product_id: int
    change: int
    old_stock: int
    new_stock: int
    action_type: str
    timestamp: datetime
    remark: Optional[str]


# ==================== ENDPOINTS =======================


# PUBLIC_INTERFACE
@app.get("/health", tags=["Health"], summary="App health check")
def health_check():
    """API Health check."""
    return {"message": "Healthy"}


# PUBLIC_INTERFACE
@app.get("/health/sqlite", tags=["Health"], summary="SQLite database connection check")
def sqlite_health():
    """Check SQLite database connection."""
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "success", "message": "Connected to SQLite database"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------- PRODUCT CRUD -----------------------


# PUBLIC_INTERFACE
@app.get(
    "/products",
    response_model=List[Product],
    tags=["Products"],
    summary="List products with optional filters"
)
def list_products(
    q: Optional[str] = Query(None, description="Search by product name or SKU"),
    min_stock: Optional[int] = Query(None, ge=0, description="Minimum stock filter"),
    max_stock: Optional[int] = Query(None, ge=0, description="Maximum stock filter"),
):
    """
    Get all products. Optional filtering by search string (matches name/sku) and stock levels.
    """
    conn = get_db()
    cursor = conn.cursor()
    base_query = "SELECT * FROM products"
    conditions = []
    values = []
    if q:
        conditions.append("(name LIKE ? OR sku LIKE ?)")
        v = f"%{q}%"
        values.extend([v, v])
    if min_stock is not None:
        conditions.append("stock >= ?")
        values.append(min_stock)
    if max_stock is not None:
        conditions.append("stock <= ?")
        values.append(max_stock)
    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)
    base_query += " ORDER BY updated_at DESC"
    cursor.execute(base_query, tuple(values))
    products = [dict(row) for row in cursor.fetchall()]
    conn.close()
    for p in products:
        for field in ("created_at", "updated_at"):
            if isinstance(p[field], str):
                p[field] = datetime.fromisoformat(p[field])
    return products


# PUBLIC_INTERFACE
@app.get(
    "/products/{product_id}",
    response_model=Product,
    tags=["Products"],
    summary="Get single product details"
)
def get_product(product_id: int):
    """
    Get a single product by its ID.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    product = dict(row)
    for field in ("created_at", "updated_at"):
        if isinstance(product[field], str):
            product[field] = datetime.fromisoformat(product[field])
    return product


# PUBLIC_INTERFACE
@app.post(
    "/products",
    response_model=Product,
    status_code=status.HTTP_201_CREATED,
    tags=["Products"],
    summary="Create new product"
)
def create_product(product: ProductCreate):
    """
    Create a new product.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        now = datetime.now().isoformat()
        cursor.execute(
            """
            INSERT INTO products (name, description, sku, price, stock, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product.name,
                product.description,
                product.sku,
                product.price,
                product.stock,
                now,
                now,
            )
        )
        product_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Integrity error: {e}")
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    conn.close()
    prod = dict(row)
    for field in ("created_at", "updated_at"):
        if isinstance(prod[field], str):
            prod[field] = datetime.fromisoformat(prod[field])
    return prod


# PUBLIC_INTERFACE
@app.put(
    "/products/{product_id}",
    response_model=Product,
    tags=["Products"],
    summary="Update existing product"
)
def update_product(product_id: int, product: ProductUpdate):
    """
    Update the details of an existing product.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    db_product = cursor.fetchone()
    if not db_product:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
    update_cols = []
    values = []
    for field in ['name', 'description', 'sku', 'price', 'stock']:
        val = getattr(product, field)
        if val is not None:
            update_cols.append(f"{field}=?")
            values.append(val)
    if not update_cols:
        conn.close()
        raise HTTPException(status_code=400, detail="No fields provided to update")
    values.append(datetime.now().isoformat())
    values.append(product_id)
    query = f"UPDATE products SET {', '.join(update_cols)}, updated_at=? WHERE id=?"
    try:
        cursor.execute(query, tuple(values))
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Integrity error: {e}")
    cursor.execute("SELECT * FROM products WHERE id=?", (product_id,))
    row = cursor.fetchone()
    conn.close()
    prod = dict(row)
    for field in ("created_at", "updated_at"):
        if isinstance(prod[field], str):
            prod[field] = datetime.fromisoformat(prod[field])
    return prod


# PUBLIC_INTERFACE
@app.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Products"],
    summary="Delete product"
)
def delete_product(product_id: int):
    """
    Delete a product from inventory.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    return


# ------------ STOCK LEVEL (ADJUSTMENTS AND TRACKING) -----------


# PUBLIC_INTERFACE
@app.post(
    "/products/{product_id}/stock",
    response_model=InventoryHistory,
    tags=["Stock"],
    summary="Modify product stock level"
)
def update_stock(product_id: int, stock_change: StockChange):
    """
    Adjust the stock level for a product (positive or negative), preserving an inventory history record.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
    old_stock = row["stock"]
    new_stock = old_stock + stock_change.change
    if new_stock < 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Insufficient stock")
    update_time = datetime.now().isoformat()
    cursor.execute(
        "UPDATE products SET stock=?, updated_at=? WHERE id=?",
        (new_stock, update_time, product_id)
    )
    cursor.execute(
        """
        INSERT INTO inventory_history (
            product_id, change, old_stock, new_stock,
            action_type, timestamp, remark
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            product_id,
            stock_change.change,
            old_stock,
            new_stock,
            "INCREMENT" if stock_change.change > 0 else "DECREMENT",
            update_time,
            stock_change.remark
        )
    )
    history_id = cursor.lastrowid
    conn.commit()
    cursor.execute(
        "SELECT * FROM inventory_history WHERE id=?",
        (history_id,)
    )
    hist = dict(cursor.fetchone())
    hist["timestamp"] = datetime.fromisoformat(hist["timestamp"])
    conn.close()
    return hist


# ---------------- INVENTORY HISTORY ENDPOINTS -------------


# PUBLIC_INTERFACE
@app.get(
    "/products/{product_id}/history",
    response_model=List[InventoryHistory],
    tags=["History"],
    summary="Get product inventory history"
)
def get_inventory_history(product_id: int):
    """
    Get inventory change history for a specific product.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM inventory_history WHERE product_id=? ORDER BY timestamp DESC",
        (product_id,)
    )
    history = [dict(row) for row in cursor.fetchall()]
    for h in history:
        h["timestamp"] = datetime.fromisoformat(h["timestamp"])
    conn.close()
    return history


# PUBLIC_INTERFACE
@app.get(
    "/history",
    response_model=List[InventoryHistory],
    tags=["History"],
    summary="Get full inventory history"
)
def get_full_inventory_history(
    limit: Optional[int] = Query(100, ge=1, le=1000, description="Limit results count")
):
    """
    Get the most recent inventory changes, across all products.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM inventory_history ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    )
    history = [dict(row) for row in cursor.fetchall()]
    for h in history:
        h["timestamp"] = datetime.fromisoformat(h["timestamp"])
    conn.close()
    return history


@app.get(
    "/docs/websocket-usage",
    tags=["Health"],
    summary="WebSocket Usage Help (N/A)",
    include_in_schema=True
)
def websocket_usage():
    """
    This inventory API only uses HTTP endpoints; there are no WebSocket interfaces available.
    """
    return {
        "info": (
            "No WebSocket APIs in this backend. "
            "Use documented HTTP endpoints for all operations."
        )
    }
