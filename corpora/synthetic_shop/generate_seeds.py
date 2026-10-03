"""Deterministic generator for the synthetic_shop seed CSVs (see DESIGN.md, "Seeds").

Run from anywhere: ``uv run python corpora/synthetic_shop/generate_seeds.py``. The output is
byte-identical on every run (fixed random seed), and the CSVs are committed, so the corpus
builds without running this script.
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


if __name__ == "__main__":
    main()
