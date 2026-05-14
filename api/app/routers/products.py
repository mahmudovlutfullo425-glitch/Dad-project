"""Product catalog and category endpoints."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import get_current_admin
from app.models import Category, Product, ProductVariant, User
from app.schemas.product import (
    CategoryOut,
    ProductCreate,
    ProductList,
    ProductOut,
    ProductUpdate,
)

router = APIRouter(tags=["products"])


def _product_query():
    """Select Product preloaded with category and variants in a single round trip."""
    return select(Product).options(
        selectinload(Product.category),
        selectinload(Product.variants),
    )


# --- Categories ---
@router.get(
    "/categories",
    response_model=list[CategoryOut],
    summary="List all categories",
)
async def list_categories(db: AsyncSession = Depends(get_db)) -> list[CategoryOut]:
    result = await db.scalars(select(Category).order_by(Category.name))
    return [CategoryOut.model_validate(c) for c in result.all()]


# --- Products: read ---
@router.get(
    "/products",
    response_model=ProductList,
    summary="List products with filtering and pagination",
)
async def list_products(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category_slug: str | None = None,
    brand: str | None = None,
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    is_active: bool | None = None,
) -> ProductList:
    stmt = _product_query()
    count_stmt = select(func.count(Product.id))

    if category_slug is not None:
        stmt = stmt.join(Product.category).where(Category.slug == category_slug)
        count_stmt = count_stmt.join(Product.category).where(Category.slug == category_slug)
    if brand is not None:
        stmt = stmt.where(Product.brand == brand)
        count_stmt = count_stmt.where(Product.brand == brand)
    if min_price is not None:
        stmt = stmt.where(Product.base_price >= min_price)
        count_stmt = count_stmt.where(Product.base_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Product.base_price <= max_price)
        count_stmt = count_stmt.where(Product.base_price <= max_price)
    if is_active is not None:
        stmt = stmt.where(Product.is_active == is_active)
        count_stmt = count_stmt.where(Product.is_active == is_active)

    total = await db.scalar(count_stmt) or 0
    stmt = stmt.order_by(Product.id).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.scalars(stmt)).unique().all()

    return ProductList(
        items=[ProductOut.model_validate(p) for p in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.get(
    "/products/{product_id}",
    response_model=ProductOut,
    summary="Fetch a single product by id",
)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)) -> ProductOut:
    product = await db.scalar(_product_query().where(Product.id == product_id))
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return ProductOut.model_validate(product)


# --- Products: write (admin only) ---
@router.post(
    "/products",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new product (admin)",
)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> ProductOut:
    category = await db.get(Category, payload.category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category {payload.category_id} does not exist",
        )

    product = Product(
        category_id=payload.category_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        brand=payload.brand,
        base_price=payload.base_price,
        attributes=payload.attributes,
        is_active=True,
    )
    for v in payload.variants:
        product.variants.append(
            ProductVariant(
                sku=v.sku,
                variant_name=v.variant_name,
                price=v.price,
                weight_grams=v.weight_grams,
            )
        )

    db.add(product)
    await db.commit()

    # Reload with relationships for the response.
    fresh = await db.scalar(_product_query().where(Product.id == product.id))
    return ProductOut.model_validate(fresh)


@router.patch(
    "/products/{product_id}",
    response_model=ProductOut,
    summary="Update a product (admin)",
)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> ProductOut:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if payload.category_id is not None:
        category = await db.get(Category, payload.category_id)
        if category is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Category {payload.category_id} does not exist",
            )

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(product, field, value)

    await db.commit()

    fresh = await db.scalar(_product_query().where(Product.id == product.id))
    return ProductOut.model_validate(fresh)


@router.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a product (admin)",
)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
) -> Response:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    product.is_active = False
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
