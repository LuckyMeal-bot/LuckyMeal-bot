import sqlite3
from pathlib import Path


# На Railway зберігаємо базу у /data (persistent volume), локально — поруч з кодом
_data_dir = Path("/data") if Path("/data").exists() else Path(".")
DB_PATH = _data_dir / "food_bot.db"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS venues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                owner_telegram_id INTEGER,
                name TEXT NOT NULL,
                address TEXT,
                phone TEXT,
                instagram TEXT,
                contact_person TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venue_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                original_price REAL NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                pickup_time TEXT NOT NULL,
                photo_file_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (venue_id) REFERENCES venues (id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_id INTEGER NOT NULL,
                buyer_telegram_id INTEGER NOT NULL,
                buyer_name TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (offer_id) REFERENCES offers (id)
            )
            """
        )

        # Migrations — додаємо колонки, яких може не бути в старій БД
        offer_columns = connection.execute("PRAGMA table_info(offers)").fetchall()
        offer_column_names = [column["name"] for column in offer_columns]

        if "original_price" not in offer_column_names:
            connection.execute("ALTER TABLE offers ADD COLUMN original_price REAL")
            connection.execute("UPDATE offers SET original_price = price")

        if "photo_file_id" not in offer_column_names:
            connection.execute("ALTER TABLE offers ADD COLUMN photo_file_id TEXT")

        venue_columns = connection.execute("PRAGMA table_info(venues)").fetchall()
        venue_column_names = [column["name"] for column in venue_columns]

        if "owner_telegram_id" not in venue_column_names:
            connection.execute("ALTER TABLE venues ADD COLUMN owner_telegram_id INTEGER")

        for column_name in ("address", "phone", "instagram", "contact_person"):
            if column_name not in venue_column_names:
                connection.execute(f"ALTER TABLE venues ADD COLUMN {column_name} TEXT")

        connection.execute(
            """
            UPDATE venues
            SET owner_telegram_id = telegram_id
            WHERE owner_telegram_id IS NULL
            """
        )


def create_or_update_venue(owner_telegram_id, name, address, phone, instagram, contact_person):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO venues (
                telegram_id,
                owner_telegram_id,
                name,
                address,
                phone,
                instagram,
                contact_person
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                owner_telegram_id = excluded.owner_telegram_id,
                name = excluded.name,
                address = excluded.address,
                phone = excluded.phone,
                instagram = excluded.instagram,
                contact_person = excluded.contact_person
            """,
            (
                owner_telegram_id,
                owner_telegram_id,
                name,
                address,
                phone,
                instagram,
                contact_person,
            ),
        )


def get_venue_by_telegram_id(telegram_id):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM venues
            WHERE telegram_id = ? OR owner_telegram_id = ?
            """,
            (telegram_id, telegram_id),
        ).fetchone()


def add_offer(owner_telegram_id, title, original_price, price, quantity, pickup_time, photo_file_id=None):
    venue = get_venue_by_telegram_id(owner_telegram_id)
    if venue is None:
        raise ValueError("Venue is not registered")

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO offers (venue_id, title, original_price, price, quantity, pickup_time, photo_file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (venue["id"], title, original_price, price, quantity, pickup_time, photo_file_id),
        )


def list_available_offers():
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                offers.id,
                offers.title,
                COALESCE(offers.original_price, offers.price) AS original_price,
                offers.price,
                offers.quantity,
                offers.pickup_time,
                offers.photo_file_id,
                venues.name AS venue_name,
                venues.address AS venue_address,
                venues.phone AS venue_phone,
                venues.instagram AS venue_instagram
            FROM offers
            JOIN venues ON venues.id = offers.venue_id
            WHERE offers.quantity > 0
            ORDER BY offers.created_at DESC
            """
        ).fetchall()


def get_offer(offer_id):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                offers.id,
                offers.title,
                COALESCE(offers.original_price, offers.price) AS original_price,
                offers.price,
                offers.quantity,
                offers.pickup_time,
                offers.photo_file_id,
                venues.name AS venue_name,
                venues.address AS venue_address,
                venues.phone AS venue_phone,
                venues.instagram AS venue_instagram,
                venues.contact_person AS venue_contact_person,
                COALESCE(venues.owner_telegram_id, venues.telegram_id) AS venue_owner_telegram_id
            FROM offers
            JOIN venues ON venues.id = offers.venue_id
            WHERE offers.id = ?
            """,
            (offer_id,),
        ).fetchone()


def confirm_booking(offer_id, buyer_telegram_id, buyer_name):
    with get_connection() as connection:
        offer = connection.execute(
            "SELECT quantity FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()

        if offer is None:
            return None, "not_found"

        if offer["quantity"] <= 0:
            return None, "sold_out"

        connection.execute(
            "UPDATE offers SET quantity = quantity - 1 WHERE id = ?",
            (offer_id,),
        )
        cursor = connection.execute(
            """
            INSERT INTO bookings (offer_id, buyer_telegram_id, buyer_name, status)
            VALUES (?, ?, ?, ?)
            """,
            (offer_id, buyer_telegram_id, buyer_name, "confirmed"),
        )
        booking_id = cursor.lastrowid

    return booking_id, "confirmed"


def list_venue_offers(owner_telegram_id):
    venue = get_venue_by_telegram_id(owner_telegram_id)
    if venue is None:
        return []

    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                id,
                title,
                COALESCE(original_price, price) AS original_price,
                price,
                quantity,
                pickup_time,
                photo_file_id
            FROM offers
            WHERE venue_id = ?
            ORDER BY created_at DESC
            """,
            (venue["id"],),
        ).fetchall()


def list_buyer_bookings(buyer_telegram_id):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                bookings.id AS booking_id,
                bookings.status,
                bookings.created_at,
                offers.title AS offer_title,
                COALESCE(offers.original_price, offers.price) AS original_price,
                offers.price,
                offers.pickup_time,
                venues.name AS venue_name,
                venues.address AS venue_address
            FROM bookings
            JOIN offers ON offers.id = bookings.offer_id
            JOIN venues ON venues.id = offers.venue_id
            WHERE bookings.buyer_telegram_id = ?
            ORDER BY bookings.created_at DESC
            LIMIT 10
            """,
            (buyer_telegram_id,),
        ).fetchall()
