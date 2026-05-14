"""Seed the database with realistic dev data.

Usage:
    docker compose run --rm api python /app/../scripts/seed.py

Or via Makefile:
    make seed
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from faker import Faker
from passlib.context import CryptContext
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from app.config import get_settings
from app.models import (
    Address,
    Category,
    FlashSale,
    FlashSaleItem,
    FlashSaleStatus,
    InventoryLevel,
    Product,
    ProductVariant,
    User,
)

fake = Faker()
random.seed(42)
Faker.seed(42)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

CATEGORY_NAMES = [
    "Electronics", "Smartphones", "Laptops", "Tablets", "Headphones",
    "Cameras", "Gaming", "Wearables", "Home Audio", "Smart Home",
    "Kitchen", "Cookware", "Coffee", "Small Appliances", "Furniture",
    "Lighting", "Bedding", "Bath", "Fashion", "Men's Clothing",
    "Women's Clothing", "Shoes", "Bags", "Accessories", "Sports",
    "Outdoor", "Fitness", "Cycling", "Running", "Hiking",
    "Beauty", "Skincare", "Haircare", "Makeup", "Fragrance",
    "Books", "Fiction", "Non-Fiction", "Children", "Toys",
    "Board Games", "Puzzles", "Office", "Stationery", "Pet Supplies",
    "Dog", "Cat", "Garden", "Tools", "Auto",
]
BRANDS = [
    "Acme", "Nova", "Vertex", "Lumen", "Quanta", "Helix", "Forge",
    "Apex", "Orbit", "Pulse", "Crest", "Drift", "Echo", "Flare", "Glide",
]


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def seed() -> None:
    settings = get_settings()
    engine = create_engine(settings.sync_database_url)

    with Session(engine) as session:
        # Idempotency check
        existing = session.execute(text("SELECT count(*) FROM users")).scalar_one()
        if existing > 0:
            print(f"Database already seeded ({existing} users). Skipping.")
            return

        print("Seeding categories...")
        categories = [
            Category(name=name, slug=name.lower().replace(" ", "-").replace("'", ""))
            for name in CATEGORY_NAMES
        ]
        session.add_all(categories)
        session.flush()

        print("Seeding users...")
        users: list[User] = []
        admin = User(
            email="admin@ecom.local",
            password_hash=hash_password("admin123"),
            full_name="Admin User",
            is_admin=True,
        )
        users.append(admin)
        for i in range(9):
            u = User(
                email=f"user{i+1}@ecom.local",
                password_hash=hash_password("user1234"),
                full_name=fake.name(),
                is_admin=False,
            )
            users.append(u)
        session.add_all(users)
        session.flush()

        print("Seeding addresses...")
        addresses = []
        for u in users:
            for j in range(random.randint(1, 2)):
                addresses.append(
                    Address(
                        user_id=u.id,
                        label="home" if j == 0 else "work",
                        line1=fake.street_address(),
                        city=fake.city(),
                        postal_code=fake.postcode(),
                        country=fake.country_code(),
                        is_default=(j == 0),
                    )
                )
        session.add_all(addresses)

        print("Seeding 1000 products with variants and inventory...")
        products: list[Product] = []
        variants: list[ProductVariant] = []
        for i in range(1000):
            cat = random.choice(categories)
            name = f"{random.choice(BRANDS)} {fake.word().capitalize()} {fake.word().capitalize()} {i+1}"
            slug = name.lower().replace(" ", "-")
            p = Product(
                category_id=cat.id,
                name=name,
                slug=slug,
                description=fake.paragraph(nb_sentences=4),
                brand=random.choice(BRANDS),
                base_price=Decimal(random.randint(500, 200000)) / 100,
                attributes={"color": random.choice(["red", "blue", "black", "white"])},
            )
            products.append(p)
        session.add_all(products)
        session.flush()

        for p in products:
            n_variants = random.choice([1, 1, 2, 3])
            for v in range(n_variants):
                variant = ProductVariant(
                    product_id=p.id,
                    sku=f"SKU-{p.id:06d}-{v+1:02d}",
                    variant_name=f"Variant {v+1}",
                    price=p.base_price + Decimal(random.randint(-200, 500)) / 100,
                    weight_grams=random.randint(100, 5000),
                )
                variants.append(variant)
        session.add_all(variants)
        session.flush()

        print(f"Seeding inventory for {len(variants)} variants...")
        inventory = [
            InventoryLevel(
                variant_id=v.id,
                quantity_on_hand=random.randint(0, 500),
                quantity_reserved=0,
                low_stock_threshold=10,
            )
            for v in variants
        ]
        session.add_all(inventory)

        print("Seeding flash sale...")
        now = datetime.now(timezone.utc)
        fs = FlashSale(
            name="Weekend Flash Sale",
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=3),
            status=FlashSaleStatus.SCHEDULED,
        )
        session.add(fs)
        session.flush()

        fs_variants = random.sample(variants, k=20)
        fs_items = []
        for v in fs_variants:
            fs_items.append(
                FlashSaleItem(
                    flash_sale_id=fs.id,
                    variant_id=v.id,
                    sale_price=v.price * Decimal("0.6"),
                    quantity_allocated=random.randint(10, 100),
                    per_user_limit=2,
                )
            )
        session.add_all(fs_items)

        session.commit()
        print("Seed complete.")
        print(f"  - {len(categories)} categories")
        print(f"  - {len(users)} users (admin@ecom.local / admin123, user1@ecom.local / user1234)")
        print(f"  - {len(addresses)} addresses")
        print(f"  - {len(products)} products")
        print(f"  - {len(variants)} variants with inventory")
        print(f"  - 1 flash sale with {len(fs_items)} items")


if __name__ == "__main__":
    seed()
