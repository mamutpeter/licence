import asyncio
import asyncpg
import os

async def create_table():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL не знайдено.")
        return

    conn = await asyncpg.connect(dsn=db_url)
    await conn.execute("""
        DROP TABLE IF EXISTS licenses;
    """)
    await conn.execute("""
        CREATE TABLE licenses (
            license_key TEXT PRIMARY KEY,
            start_date TEXT,
            end_date TEXT
        )
    """)
    await conn.close()
    print("✅ Таблиця 'licenses' створена (з license_key).")

if __name__ == "__main__":
    asyncio.run(create_table())
