"""Deterministic generator for the synthetic_shop seed CSVs (DESIGN.md "Seeds", DESIGN_v2 §2, §7.2).

Run from anywhere: ``uv run python corpora/synthetic_shop/generate_seeds.py``. The output is
byte-identical on every run (fixed random seed), and the CSVs are committed, so the corpus
builds without running this script.

v1 rows come from ``RNG`` exactly as before. Everything added for v2 (8 new seeds, the appended
``cancelled`` orders and the one unsold product) comes from ``V2_RNG``, after the v1 rows, so the
v1 values never shift. The only v1 CSV changes are rows appended to ``raw_orders`` and
``raw_products`` (DESIGN_v2 §1 item 4).
"""

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SEEDS_DIR = Path(__file__).parent / "seeds"
RNG = random.Random(42)

N_CUSTOMERS = 50
N_ORDERS = 200
FIRST_DAY = date(2025, 1, 1)
LAST_DAY = date(2025, 12, 31)

FIRST_NAMES = [
    "Ava", "Liam", "Maya", "Noah", "Zoe", "Ethan", "Priya", "Lucas", "Mei", "Omar",
    "Sofia", "Jonas", "Aisha", "Mateo", "Hana", "Felix", "Nora", "Ravi", "Clara", "Theo",
]  # fmt: skip
LAST_NAMES = [
    "Nguyen", "Smith", "Patel", "Garcia", "Kim", "Muller", "Rossi", "Silva", "Khan", "Brown",
    "Ivanov", "Sato", "Dubois", "Lopez", "Novak",
]  # fmt: skip
COUNTRIES = ["us", "gb", "de", "fr", "in", "jp", "br", "ca"]
PAYMENT_METHODS = ["card", "paypal", "bank_transfer", "gift_card"]
REFUND_REASONS = ["damaged", "wrong_item", "changed_mind", "late_delivery"]
PRODUCTS = [
    ("Trail Backpack", "outdoor", 89.00),
    ("Insulated Bottle", "outdoor", 24.50),
    ("Camp Stove", "outdoor", 59.99),
    ("Headlamp", "outdoor", 34.00),
    ("Running Shoes", "apparel", 120.00),
    ("Rain Jacket", "apparel", 99.00),
    ("Wool Socks", "apparel", 14.50),
    ("Fleece Hoodie", "apparel", 65.00),
    ("Desk Lamp", "home", 42.00),
    ("Ceramic Mug", "home", 12.00),
    ("Throw Blanket", "home", 38.50),
    ("French Press", "home", 29.99),
    ("Notebook Set", "office", 16.00),
    ("Mechanical Keyboard", "office", 109.00),
    ("Monitor Stand", "office", 45.00),
]  # (name, category, list_price)

# v2 (DESIGN_v2 §1 item 4): one product with costs and stock but no sales, appended as id 16.
UNSOLD_PRODUCT = ("Camp Chair", "outdoor", 49.00)
N_CANCELLED = 8

# Orders per customer: 8 with none, 10 with one, 26 with 2-3, 6 with 4+ (sums to 200 below).
ZERO, ONE, MID, HEAVY = 8, 10, 26, 6


def money(x: float) -> str:
    return f"{x:.2f}"


def order_counts() -> list[int]:
    counts = [0] * ZERO + [1] * ONE + [RNG.choice([2, 3]) for _ in range(MID)]
    counts += [4] * HEAVY
    # Distribute the remaining orders across the heavy customers (all stay at 4+).
    remaining = N_ORDERS - sum(counts)
    heavy_start = len(counts) - HEAVY
    while remaining > 0:
        counts[heavy_start + RNG.randrange(HEAVY)] += 1
        remaining -= 1
    RNG.shuffle(counts)
    return counts


def random_day() -> date:
    return FIRST_DAY + timedelta(days=RNG.randrange((LAST_DAY - FIRST_DAY).days + 1))


def stamp(day: date, extra_days: int = 0) -> str:
    moment = datetime.combine(day + timedelta(days=extra_days), datetime.min.time())
    moment += timedelta(seconds=RNG.randrange(86_400))
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def write(name: str, header: list[str], rows: list[list[object]]) -> None:
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SEEDS_DIR / f"{name}.csv", "w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    print(f"{name}: {len(rows)} rows")


# ----------------------------------------------------------------------------- v2 (DESIGN_v2)
V2_RNG = random.Random(2026)

CARRIERS = ["UPS", " ups", "DHL ", "FedEx", "fedex "]  # lower(trim()) gives 3 carriers
SESSION_CHANNELS = ["Direct", "organic", "Paid_Search", "SOCIAL", "email"]
SPEND_CHANNELS = ["Paid_Search", "SOCIAL", "Email"]
CAMPAIGNS = {
    "paid_search": ["brand_search", "generic_search"],
    "social": ["spring_social", "holiday_social"],
    "email": ["newsletter", "winback"],
}
PROMOTIONS = [  # (code, discount_pct, channel); `internal` ones are dropped by int_order_promotions
    ("spring10", 10, "email"),
    ("Welcome15", 15, "social"),
    ("SEARCH5", 5, "paid_search"),
    ("holiday20", 20, "email"),
    ("staff30", 30, "internal"),
    ("Flash25", 25, "social"),
    ("qa_test50", 50, "internal"),
    ("loyal12", 12, "email"),
]
SUPPLIERS = [  # (name, country, lead_time_days); upper(country) in staging
    ("Northwind Outfitters", "us", 7),
    ("Alpen Supply GmbH", "de", 14),
    ("Kanto Goods", "jp", 21),
    ("Maple Trading", "Ca", 10),
    ("Rio Textiles", "br", 28),
]
WAREHOUSES = ["wh_east", "wh_west", "wh_test"]  # upper() in staging; WH_TEST is filtered out


def cancelled_orders(orders: list[list[object]]) -> list[list[object]]:
    """`cancelled` orders (the `else 'other'` branch of order_status_group, DESIGN_v2 §7.2).

    Only customers who already have v1 orders, dates inside the v1 range, tax 0, and no items,
    payments, refunds, shipments or promotions.
    """
    customers = sorted({int(str(o[1])) for o in orders})
    days = sorted(date.fromisoformat(str(o[2])) for o in orders)
    span = (days[-1] - days[0]).days
    rows: list[list[object]] = []
    for i in range(N_CANCELLED):
        day = days[0] + timedelta(days=V2_RNG.randrange(span + 1))
        rows.append([len(orders) + i + 1, V2_RNG.choice(customers), day.isoformat(), "cancelled",
                     money(0)])  # fmt: skip
    return rows


def v2_stamp(day: date, extra_days: int = 0) -> str:
    moment = datetime.combine(day + timedelta(days=extra_days), datetime.min.time())
    moment += timedelta(seconds=V2_RNG.randrange(86_400))
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def shipments(orders: list[list[object]]) -> list[list[object]]:
    """0..2 per order; placed orders mostly have none or a not-yet-shipped row (null shipped_at)."""
    rows: list[list[object]] = []
    for oid, _, day_iso, status, _ in orders:
        day = date.fromisoformat(str(day_iso))
        if status == "placed":
            n = V2_RNG.choice([0, 0, 1])
        else:
            n = V2_RNG.choice([0, 1, 1, 1, 1, 2])
        for _ in range(n):
            cost = money(V2_RNG.uniform(3.5, 25))
            carrier = V2_RNG.choice(CARRIERS)
            if status == "placed":
                rows.append([len(rows) + 1, oid, carrier, "", "", cost])
                continue
            ship_offset = V2_RNG.randint(0, 3)
            shipped = v2_stamp(day, ship_offset)
            in_transit = status == "shipped" and V2_RNG.random() < 0.25
            delivered = "" if in_transit else v2_stamp(day, ship_offset + V2_RNG.randint(2, 9))
            rows.append([len(rows) + 1, oid, carrier, shipped, delivered, cost])
    return rows


def web_sessions(orders: list[list[object]]) -> list[list[object]]:
    """Sessions before orders (some same-day, some orders with several), anonymous traffic, bots
    and empty sessions. Customers with id % 9 == 0 never visit (customers with no sessions)."""
    rows: list[list[object]] = []

    def add(user: object, day: date, bot: bool = False, views: int | None = None) -> None:
        channel = V2_RNG.choice(SESSION_CHANNELS)
        key = channel.lower()
        campaign = "" if key in ("direct", "organic") else V2_RNG.choice(CAMPAIGNS[key])
        pages = views if views is not None else V2_RNG.randint(1, 12)
        rows.append([len(rows) + 1, user, v2_stamp(day), channel, campaign, pages,
                     "true" if bot else "false"])  # fmt: skip

    for _, cid, day_iso, _, _ in orders:
        if int(str(cid)) % 9 == 0:
            continue
        day = date.fromisoformat(str(day_iso))
        for _ in range(V2_RNG.choice([0, 1, 1, 2, 3])):
            add(cid, day - timedelta(days=V2_RNG.choice([0, 0, 1, 3, 7, 14, 30])))
    for _ in range(120):  # anonymous visitors
        add("", random_v2_day())
    for _ in range(30):  # bots
        add(V2_RNG.choice(["", V2_RNG.randint(1, N_CUSTOMERS)]), random_v2_day(), bot=True)
    for _ in range(25):  # empty sessions (page_views = 0)
        add(V2_RNG.choice(["", V2_RNG.randint(1, 8)]), random_v2_day(), views=0)
    rows.sort(key=lambda r: (str(r[2]), int(str(r[0]))))
    return [[i, *r[1:]] for i, r in enumerate(rows, start=1)]


def random_v2_day() -> date:
    return FIRST_DAY + timedelta(days=V2_RNG.randrange((LAST_DAY - FIRST_DAY).days + 1))


def marketing_spend() -> list[list[object]]:
    """One row per day x channel x campaign on most days (some days have no spend)."""
    rows: list[list[object]] = []
    day = FIRST_DAY
    while day <= LAST_DAY:
        for channel in SPEND_CHANNELS:
            if V2_RNG.random() < 0.2:
                continue
            for campaign in CAMPAIGNS[channel.lower()]:
                if V2_RNG.random() < 0.5:
                    continue
                impressions = V2_RNG.randint(200, 5000)
                clicks = V2_RNG.randint(0, impressions // 20)
                spend = money(V2_RNG.uniform(5, 120))
                rows.append([day.isoformat(), channel, campaign, spend, impressions, clicks])
        day += timedelta(days=1)
    return rows


def promotions() -> list[list[object]]:
    rows: list[list[object]] = []
    for i, (code, pct, channel) in enumerate(PROMOTIONS, start=1):
        start = FIRST_DAY + timedelta(days=V2_RNG.randrange(0, 200))
        end = start + timedelta(days=V2_RNG.randint(30, 160))
        rows.append([i, code, money(pct), start.isoformat(), end.isoformat(), channel])
    return rows


def order_promotions(orders: list[list[object]]) -> list[list[object]]:
    """0..2 distinct promotions per order; some orders use only an `internal` promotion."""
    rows: list[list[object]] = []
    for oid, *_ in orders:
        n = V2_RNG.choice([0, 0, 0, 1, 1, 2])
        for pid in V2_RNG.sample(range(1, len(PROMOTIONS) + 1), n):
            rows.append([len(rows) + 1, oid, pid, money(V2_RNG.uniform(2, 30))])
    return rows


def suppliers() -> list[list[object]]:
    return [[i, n, c, d] for i, (n, c, d) in enumerate(SUPPLIERS, start=1)]


def product_costs(products: list[list[object]]) -> list[list[object]]:
    """Every product has >= 1 cost row (the INNER JOINs drop nothing); every 3rd has a cost history
    (QUALIFY keeps the latest); products 5 and 14 have a latest cost near list price, so some
    lines lose money."""
    rows: list[list[object]] = []
    for pid, _, _, list_price in products:
        price = float(str(list_price))
        history = 3 if int(str(pid)) % 3 == 0 else 1
        valid = date(2024, 1, 1) + timedelta(days=V2_RNG.randrange(0, 120))
        for step in range(history):
            share = V2_RNG.uniform(0.35, 0.7)
            if int(str(pid)) in (5, 14) and step == history - 1:
                share = V2_RNG.uniform(0.95, 1.1)
            supplier = V2_RNG.randint(1, len(SUPPLIERS))
            rows.append([len(rows) + 1, pid, supplier, money(price * share), valid.isoformat()])
            valid += timedelta(days=V2_RNG.randint(60, 200))
    return rows


def inventory_snapshots(products: list[list[object]]) -> list[list[object]]:
    """Month-start snapshots per product x warehouse; every product is stocked in wh_east and
    wh_west; about a third also have test-warehouse rows."""
    rows: list[list[object]] = []
    for pid, *_ in products:
        houses = WAREHOUSES if V2_RNG.random() < 0.35 else WAREHOUSES[:2]
        for wh in houses:
            qty = V2_RNG.randint(20, 200)
            for month in range(1, 13):
                qty = max(0, qty + V2_RNG.randint(-30, 25))
                rows.append([0, pid, date(2025, month, 1).isoformat(), qty, wh])
    return [[i, *r[1:]] for i, r in enumerate(rows, start=1)]


def main_v2(orders: list[list[object]], products: list[list[object]]) -> None:
    """The 8 v2 seeds. `orders` are the v1 orders only: cancelled orders get no shipments or
    promotions, and sessions are generated around real orders."""
    write(
        "raw_shipments",
        ["id", "order_id", "carrier", "shipped_at", "delivered_at", "shipping_cost_usd"],
        shipments(orders),
    )
    write(
        "raw_web_sessions",
        ["id", "user_id", "started_at", "channel", "utm_campaign", "page_views", "is_bot"],
        web_sessions(orders),
    )
    write(
        "raw_marketing_spend",
        ["spend_day", "channel", "campaign", "spend_usd", "impressions", "clicks"],
        marketing_spend(),
    )
    write(
        "raw_promotions",
        ["id", "code", "discount_pct", "starts_at", "ends_at", "channel"],
        promotions(),
    )
    write(
        "raw_order_promotions",
        ["id", "order_id", "promotion_id", "discount_usd"],
        order_promotions(orders),
    )
    write("raw_suppliers", ["id", "name", "country", "lead_time_days"], suppliers())
    write(
        "raw_product_costs",
        ["id", "product_id", "supplier_id", "unit_cost", "valid_from"],
        product_costs(products),
    )
    write(
        "raw_inventory_snapshots",
        ["id", "product_id", "snapshot_date", "qty_on_hand", "warehouse"],
        inventory_snapshots(products),
    )


def main() -> None:
    counts = order_counts()

    customers: list[list[object]] = []
    for cid in range(1, N_CUSTOMERS + 1):
        first, last = RNG.choice(FIRST_NAMES), RNG.choice(LAST_NAMES)
        # Mixed case and stray spaces give the staging trim/lower/upper something to clean.
        email = f" {first}.{last}{cid}@Example.com ".lower() if cid % 7 == 0 else None
        email = email or f"{first}.{last}{cid}@example.com".lower()
        signup = FIRST_DAY - timedelta(days=RNG.randrange(1, 400))
        customers.append([cid, first, last, email, RNG.choice(COUNTRIES), stamp(signup)])
    write(
        "raw_customers",
        ["id", "first_name", "last_name", "email", "country", "created_at"],
        customers,
    )

    products = [[i, n, c, money(p)] for i, (n, c, p) in enumerate(PRODUCTS, start=1)]
    products.append([len(PRODUCTS) + 1, *UNSOLD_PRODUCT[:2], money(UNSOLD_PRODUCT[2])])
    write("raw_products", ["id", "name", "category", "list_price"], products)

    # Same-day orders for a customer come from reusing a day for 1 in 6 follow-up orders.
    order_customers = [cid for cid, n in enumerate(counts, start=1) for _ in range(n)]
    RNG.shuffle(order_customers)
    days: dict[int, list[date]] = {}
    orders: list[list[object]] = []
    items: list[list[object]] = []
    payments: list[list[object]] = []
    refunds: list[list[object]] = []
    item_id = payment_id = refund_id = 0

    for oid, cid in enumerate(order_customers, start=1):
        seen = days.setdefault(cid, [])
        day = RNG.choice(seen) if seen and RNG.random() < 1 / 6 else random_day()
        seen.append(day)

        subtotal = 0.0
        for _ in range(RNG.randint(1, 4)):
            item_id += 1
            pid = RNG.randint(1, len(PRODUCTS))
            list_price = PRODUCTS[pid - 1][2]
            discounted = RNG.random() < 0.30
            price = (
                round(list_price * RNG.choice([0.8, 0.85, 0.9]), 2) if discounted else list_price
            )
            qty = RNG.randint(1, 3)
            subtotal += qty * price
            items.append([item_id, oid, pid, qty, money(price)])
        tax = round(subtotal * 0.08, 2)

        refunded = RNG.random() < 0.15
        status = (
            RNG.choice(["return_pending", "returned"])
            if refunded
            else RNG.choice(["placed", "shipped", "completed", "completed", "completed"])
        )
        orders.append([oid, cid, day.isoformat(), status, money(tax)])

        total = round(subtotal + tax, 2)
        if RNG.random() >= 0.03:  # a few unpaid orders (0 payments)
            n_pay = RNG.choice([1, 1, 2])
            first_part = round(total * RNG.choice([0.4, 0.5, 0.6]), 2) if n_pay == 2 else total
            amounts = [first_part] + ([round(total - first_part, 2)] if n_pay == 2 else [])
            for amt in amounts:
                payment_id += 1
                payments.append(
                    [payment_id, oid, RNG.choice(PAYMENT_METHODS), money(amt), stamp(day, 0)]
                )
        if refunded:
            for _ in range(RNG.choice([1, 1, 2])):
                refund_id += 1
                amt = round(subtotal * RNG.choice([0.2, 0.35, 0.5]), 2)
                refunds.append(
                    [refund_id, oid, money(amt), RNG.choice(REFUND_REASONS), stamp(day, 5)]
                )

    v1_orders = list(orders)
    orders += cancelled_orders(orders)
    write("raw_orders", ["id", "user_id", "order_date", "status", "tax_usd"], orders)
    write(
        "raw_order_items",
        ["id", "order_id", "product_id", "quantity", "unit_price"],
        items,
    )
    write(
        "raw_payments",
        ["id", "order_id", "method", "amt", "created_at"],
        payments,
    )
    write(
        "raw_refunds",
        ["id", "order_id", "refund_amt", "reason", "created_at"],
        refunds,
    )
    main_v2(v1_orders, products)


if __name__ == "__main__":
    main()
