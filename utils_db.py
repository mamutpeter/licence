import os
import asyncpg
from datetime import date

DATABASE_URL = os.getenv("DATABASE_URL")

# 1. Пул підключення
async def get_pool():
    if not hasattr(get_pool, "pool"):
        get_pool.pool = await asyncpg.create_pool(DATABASE_URL)
    return get_pool.pool

# 2. Створення таблиці (якщо не існує)
async def ensure_tables():
    pool = await get_pool()
    await pool.execute("""
    CREATE TABLE IF NOT EXISTS licenses (
        id SERIAL PRIMARY KEY,
        group_type TEXT NOT NULL,
        store_id TEXT NOT NULL,
        license_type TEXT NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        UNIQUE (group_type, store_id, license_type)
    );
    """)

# 3. Додати або оновити ліцензію
async def upsert_license(group_, store_id, lic_type, start_, end_):
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO licenses (group_type, store_id, license_type, start_date, end_date)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (group_type, store_id, license_type)
        DO UPDATE SET start_date=$4, end_date=$5
        """,
        group_, store_id, lic_type, start_, end_
    )

# 4. Отримати ліцензію
async def fetch_license(group_, store_id, lic_type):
    pool = await get_pool()
    return await pool.fetchrow(
        """
        SELECT start_date, end_date
        FROM licenses
        WHERE group_type = $1 AND store_id = $2 AND license_type = $3
        """,
        group_, store_id, lic_type
    )

# 5. Ліцензії, що закінчуються через N днів
async def licenses_expiring(days: int):
    pool = await get_pool()
    return await pool.fetch(
        """
        SELECT group_type, store_id, license_type, end_date
        FROM licenses
        WHERE end_date = CURRENT_DATE + $1::int
        """,
        days
    )
