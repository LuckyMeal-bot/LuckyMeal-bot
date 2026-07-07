import sqlite3
from datetime import date
from pathlib import Path

_data_dir = Path("/data") if Path("/data").exists() else Path(".")
DB_PATH = _data_dir / "food_bot.db"

VENUE_CATEGORIES = [
    "🍝 Паста / Ризото",
    "🍕 Піца",
    "🥗 Салат-бар",
    "🍔 Бургери",
    "🥩 М'ясо / Гриль",
    "🦞 Морепродукти",
    "☕ Кафе",
    "🍽️ Інше",
]


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS venues (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id      INTEGER UNIQUE,
                owner_telegram_id INTEGER,
                name             TEXT NOT NULL,
                category         TEXT,
                address          TEXT,
                phone            TEXT,
                instagram        TEXT,
                contact_person   TEXT,
                description      TEXT,
                photo_url        TEXT,
                pickup           INTEGER DEFAULT 1,
                status           TEXT    DEFAULT 'active',
                admin_managed    INTEGER DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS offers (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                venue_id       INTEGER NOT NULL,
                title          TEXT    NOT NULL,
                original_price REAL    NOT NULL,
                price          REAL    NOT NULL,
                quantity       INTEGER NOT NULL,
                pickup_time    TEXT    NOT NULL,
                photo_file_id  TEXT,
                template_id    INTEGER,
                active_date    TEXT,
                created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (venue_id)   REFERENCES venues (id),
                FOREIGN KEY (template_id) REFERENCES templates (id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_id          INTEGER NOT NULL,
                buyer_telegram_id INTEGER NOT NULL,
                buyer_name        TEXT    NOT NULL,
                status            TEXT    NOT NULL,
                created_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (offer_id) REFERENCES offers (id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS templates (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                venue_id       INTEGER NOT NULL,
                title          TEXT    NOT NULL,
                original_price REAL    NOT NULL,
                price          REAL    NOT NULL,
                pickup_time    TEXT    NOT NULL,
                photo_file_id  TEXT,
                description    TEXT,
                created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (venue_id) REFERENCES venues (id)
            )
            """
        )

        # ── Migrations ─────────────────────────────────────────────────────────
        venue_cols = {
            col["name"]: col
            for col in connection.execute("PRAGMA table_info(venues)").fetchall()
        }

        # telegram_id had NOT NULL in old schema → recreate table to allow NULL
        if venue_cols.get("telegram_id", {}).get("notnull") == 1:
            connection.execute(
                """
                CREATE TABLE venues_v2 (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id      INTEGER UNIQUE,
                    owner_telegram_id INTEGER,
                    name             TEXT NOT NULL,
                    category         TEXT,
                    address          TEXT,
                    phone            TEXT,
                    instagram        TEXT,
                    contact_person   TEXT,
                    description      TEXT,
                    photo_url        TEXT,
                    pickup           INTEGER DEFAULT 1,
                    status           TEXT    DEFAULT 'active',
                    admin_managed    INTEGER DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                INSERT INTO venues_v2
                    (id, telegram_id, owner_telegram_id, name, address, phone, instagram, contact_person)
                SELECT id, telegram_id, owner_telegram_id, name, address, phone, instagram, contact_person
                FROM venues
                """
            )
            connection.execute("DROP TABLE venues")
            connection.execute("ALTER TABLE venues_v2 RENAME TO venues")
            venue_cols = {
                col["name"]: col
                for col in connection.execute("PRAGMA table_info(venues)").fetchall()
            }

        # Add any missing venue columns
        for col_name, col_def in {
            "category":       "TEXT",
            "description":    "TEXT",
            "photo_url":      "TEXT",
            "pickup":         "INTEGER DEFAULT 1",
            "status":         "TEXT DEFAULT 'active'",
            "admin_managed":  "INTEGER DEFAULT 0",
            "contact_person": "TEXT",
            "instagram":      "TEXT",
            "phone":          "TEXT",
            "address":        "TEXT",
        }.items():
            if col_name not in venue_cols:
                connection.execute(f"ALTER TABLE venues ADD COLUMN {col_name} {col_def}")

        offer_col_names = {
            col["name"]
            for col in connection.execute("PRAGMA table_info(offers)").fetchall()
        }
        if "original_price" not in offer_col_names:
            connection.execute("ALTER TABLE offers ADD COLUMN original_price REAL")
            connection.execute("UPDATE offers SET original_price = price")
        if "photo_file_id" not in offer_col_names:
            connection.execute("ALTER TABLE offers ADD COLUMN photo_file_id TEXT")
        if "template_id" not in offer_col_names:
            connection.execute("ALTER TABLE offers ADD COLUMN template_id INTEGER")
        if "active_date" not in offer_col_names:
            connection.execute("ALTER TABLE offers ADD COLUMN active_date TEXT")

        # Backfill defaults
        connection.execute(
            "UPDATE venues SET owner_telegram_id = telegram_id "
            "WHERE owner_telegram_id IS NULL AND telegram_id IS NOT NULL"
        )
        connection.execute("UPDATE venues SET status = 'active' WHERE status IS NULL")
        connection.execute("UPDATE venues SET pickup = 1 WHERE pickup IS NULL")
        connection.execute("UPDATE venues SET admin_managed = 0 WHERE admin_managed IS NULL")


# ── Venue reads ────────────────────────────────────────────────────────────────

def get_venue_by_telegram_id(telegram_id):
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM venues WHERE telegram_id = ? OR owner_telegram_id = ?",
            (telegram_id, telegram_id),
        ).fetchone()


def get_venue_by_id(venue_id):
    with get_connection() as connection:
        return connection.execute("SELECT * FROM venues WHERE id = ?", (venue_id,)).fetchone()


def get_all_venues():
    with get_connection() as connection:
        return connection.execute("SELECT * FROM venues ORDER BY name").fetchall()


# ── Venue writes ───────────────────────────────────────────────────────────────

def create_or_update_venue(owner_telegram_id, name, address, phone, instagram, contact_person):
    """Called when a venue owner self-registers through Telegram."""
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO venues
                (telegram_id, owner_telegram_id, name, address, phone, instagram, contact_person, status, admin_managed)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0)
            ON CONFLICT(telegram_id) DO UPDATE SET
                owner_telegram_id = excluded.owner_telegram_id,
                name              = excluded.name,
                address           = excluded.address,
                phone             = excluded.phone,
                instagram         = excluded.instagram,
                contact_person    = excluded.contact_person
            """,
            (owner_telegram_id, owner_telegram_id, name, address, phone, instagram, contact_person),
        )


def admin_add_venue(name, category, address, phone, instagram, description, pickup, status="active"):
    """Admin manually adds a venue (no Telegram owner yet)."""
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO venues (name, category, address, phone, instagram, description, pickup, status, admin_managed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (name, category, address or None, phone or None,
             instagram or None, description or None, pickup, status),
        )
        return cursor.lastrowid


def admin_update_venue(venue_id, **kwargs):
    allowed = {
        "name", "category", "address", "phone", "instagram",
        "description", "photo_url", "pickup", "status", "contact_person",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with get_connection() as connection:
        connection.execute(
            f"UPDATE venues SET {set_clause} WHERE id = ?",
            [*fields.values(), venue_id],
        )


def admin_delete_venue(venue_id):
    with get_connection() as connection:
        connection.execute("UPDATE offers SET quantity = 0 WHERE venue_id = ?", (venue_id,))
        connection.execute("DELETE FROM offers WHERE venue_id = ?", (venue_id,))
        connection.execute("DELETE FROM templates WHERE venue_id = ?", (venue_id,))
        connection.execute("DELETE FROM venues WHERE id = ?", (venue_id,))


def link_venue_to_owner(venue_id, owner_telegram_id):
    """Attach a real Telegram owner to an admin-managed venue."""
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE venues
            SET telegram_id = ?, owner_telegram_id = ?, admin_managed = 0
            WHERE id = ?
            """,
            (owner_telegram_id, owner_telegram_id, venue_id),
        )


# ── Offer helpers ──────────────────────────────────────────────────────────────

def add_offer(owner_telegram_id, title, original_price, price, quantity, pickup_time, photo_file_id=None):
    venue = get_venue_by_telegram_id(owner_telegram_id)
    if venue is None:
        raise ValueError("Venue not found")
    add_offer_by_venue_id(venue["id"], title, original_price, price, quantity, pickup_time, photo_file_id)


def add_offer_by_venue_id(venue_id, title, original_price, price, quantity, pickup_time, photo_file_id=None):
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO offers (venue_id, title, original_price, price, quantity, pickup_time, photo_file_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (venue_id, title, original_price, price, quantity, pickup_time, photo_file_id),
        )


def list_available_offers():
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                offers.id, offers.title,
                COALESCE(offers.original_price, offers.price) AS original_price,
                offers.price, offers.quantity, offers.pickup_time, offers.photo_file_id,
                venues.name    AS venue_name,
                venues.address AS venue_address,
                venues.phone   AS venue_phone,
                venues.instagram AS venue_instagram
            FROM offers
            JOIN venues ON venues.id = offers.venue_id
            WHERE offers.quantity > 0 AND venues.status = 'active'
            ORDER BY offers.created_at DESC
            """
        ).fetchall()


def get_offer(offer_id):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                offers.id, offers.title,
                COALESCE(offers.original_price, offers.price) AS original_price,
                offers.price, offers.quantity, offers.pickup_time, offers.photo_file_id,
                venues.name           AS venue_name,
                venues.address        AS venue_address,
                venues.phone          AS venue_phone,
                venues.instagram      AS venue_instagram,
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
        offer = connection.execute("SELECT quantity FROM offers WHERE id = ?", (offer_id,)).fetchone()
        if offer is None:
            return None, "not_found"
        if offer["quantity"] <= 0:
            return None, "sold_out"
        connection.execute("UPDATE offers SET quantity = quantity - 1 WHERE id = ?", (offer_id,))
        cursor = connection.execute(
            "INSERT INTO bookings (offer_id, buyer_telegram_id, buyer_name, status) VALUES (?, ?, ?, 'confirmed')",
            (offer_id, buyer_telegram_id, buyer_name),
        )
        return cursor.lastrowid, "confirmed"


def list_venue_offers(owner_telegram_id):
    venue = get_venue_by_telegram_id(owner_telegram_id)
    if venue is None:
        return []
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT id, title, COALESCE(original_price, price) AS original_price,
                   price, quantity, pickup_time, photo_file_id
            FROM offers WHERE venue_id = ? ORDER BY created_at DESC
            """,
            (venue["id"],),
        ).fetchall()


def list_buyer_bookings(buyer_telegram_id):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                bookings.id   AS booking_id,
                bookings.status,
                bookings.created_at,
                offers.title  AS offer_title,
                COALESCE(offers.original_price, offers.price) AS original_price,
                offers.price,
                offers.pickup_time,
                venues.name    AS venue_name,
                venues.address AS venue_address
            FROM bookings
            JOIN offers ON offers.id = bookings.offer_id
            JOIN venues ON venues.id = offers.venue_id
            WHERE bookings.buyer_telegram_id = ?
            ORDER BY bookings.created_at DESC LIMIT 10
            """,
            (buyer_telegram_id,),
        ).fetchall()


def get_stats():
    with get_connection() as connection:
        return {
            "venues_total":    connection.execute("SELECT COUNT(*) FROM venues").fetchone()[0],
            "venues_active":   connection.execute("SELECT COUNT(*) FROM venues WHERE status='active'").fetchone()[0],
            "offers_active":   connection.execute("SELECT COUNT(*) FROM offers WHERE quantity > 0").fetchone()[0],
            "bookings_total":  connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
            "templates_total": connection.execute("SELECT COUNT(*) FROM templates").fetchone()[0],
        }


# ── Templates ──────────────────────────────────────────────────────────────────

def create_template(venue_id, title, original_price, price, pickup_time,
                    photo_file_id=None, description=None):
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO templates (venue_id, title, original_price, price, pickup_time, photo_file_id, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (venue_id, title, original_price, price, pickup_time, photo_file_id, description),
        )
        return cursor.lastrowid


def get_templates_for_venue(venue_id):
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM templates WHERE venue_id = ? ORDER BY created_at",
            (venue_id,),
        ).fetchall()


def get_template(template_id):
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM templates WHERE id = ?", (template_id,)
        ).fetchone()


def update_template(template_id, **kwargs):
    allowed = {"title", "original_price", "price", "pickup_time", "photo_file_id", "description"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with get_connection() as connection:
        connection.execute(
            f"UPDATE templates SET {set_clause} WHERE id = ?",
            [*fields.values(), template_id],
        )


def delete_template(template_id):
    with get_connection() as connection:
        connection.execute(
            "UPDATE offers SET quantity = 0 WHERE template_id = ?", (template_id,)
        )
        connection.execute("DELETE FROM templates WHERE id = ?", (template_id,))


def activate_template_today(template_id, quantity):
    """Create or update today's offer from this template. Returns offer_id."""
    today = date.today().isoformat()
    template = get_template(template_id)
    if not template:
        return None
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM offers WHERE template_id = ? AND active_date = ?",
            (template_id, today),
        ).fetchone()
        if existing:
            connection.execute(
                "UPDATE offers SET quantity = ? WHERE id = ?",
                (quantity, existing["id"]),
            )
            return existing["id"]
        cursor = connection.execute(
            "INSERT INTO offers "
            "(venue_id, title, original_price, price, quantity, pickup_time, photo_file_id, template_id, active_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                template["venue_id"], template["title"], template["original_price"],
                template["price"], quantity, template["pickup_time"],
                template["photo_file_id"], template_id, today,
            ),
        )
        return cursor.lastrowid


def deactivate_template_today(template_id):
    """Set quantity=0 for today's template offer."""
    today = date.today().isoformat()
    with get_connection() as connection:
        connection.execute(
            "UPDATE offers SET quantity = 0 WHERE template_id = ? AND active_date = ?",
            (template_id, today),
        )


def is_template_active_today(template_id):
    """Returns True if there is a live (quantity > 0) offer for this template today."""
    today = date.today().isoformat()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id FROM offers WHERE template_id = ? AND active_date = ? AND quantity > 0",
            (template_id, today),
        ).fetchone()
        return row is not None


def reset_expired_template_offers():
    """Set quantity=0 for all template-based offers from previous days. Called at midnight."""
    today = date.today().isoformat()
    with get_connection() as connection:
        connection.execute(
            "UPDATE offers SET quantity = 0 WHERE template_id IS NOT NULL AND active_date < ?",
            (today,),
        )


def get_all_venue_owner_ids():
    """Return distinct owner_telegram_ids for active venues that have at least one template."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT v.owner_telegram_id
            FROM venues v
            JOIN templates t ON t.venue_id = v.id
            WHERE v.status = 'active' AND v.owner_telegram_id IS NOT NULL
            """
        ).fetchall()
        return [row["owner_telegram_id"] for row in rows]
