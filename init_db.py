import asyncio
import asyncpg
import os

async def create_table():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL не знайдено.")
        return

    conn = await asyncpg.connect(dsn=db_url)

    # Видаляємо стару таблицю, якщо є (не переживай, дані втратиш, але структура буде правильною)
    await conn.execute("""
        DROP TABLE IF EXISTS licenses;
    """)

    # Створюємо нову правильну таблицю
    await conn.execute("""
        CREATE TABLE licenses (
            key TEXT PRIMARY KEY,
            start_date TEXT,
            end_date TEXT
        );
    """)
    await conn.close()
    print("✅ Таблиця 'licenses' створена (стара — видалена).")

if __name__ == "__main__":
    asyncio.run(create_table())
