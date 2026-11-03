"""Shopping cart for the checkout service.

A Cart holds line items for one customer. Prices are in cents to avoid float rounding.
"""

from dataclasses import dataclass


@dataclass
class LineItem:
    sku: str
    unit_price_cents: int
    quantity: int = 1

    @property
    def subtotal_cents(self) -> int:
        return self.unit_price_cents * self.quantity


class Cart:
    BULK_THRESHOLD = 10  # 10 or more units of one SKU get the bulk discount
    BULK_DISCOUNT = 0.10

    def __init__(self, customer_id, items=[]):
        self.customer_id = customer_id
        self.items = items

    def add(self, sku, unit_price_cents, quantity=1):
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        for item in self.items:
            if item.sku == sku:
                item.quantity += quantity
                return item
        item = LineItem(sku, unit_price_cents, quantity)
        self.items.append(item)
        return item

    def remove(self, sku):
        self.items = [i for i in self.items if i.sku != sku]

    def item_count(self):
        return sum(i.quantity for i in self.items)

    def total_cents(self):
        total = 0
        for item in self.items:
            line = item.subtotal_cents
            if item.quantity >= self.BULK_THRESHOLD:
                line = round(line * (1 - self.BULK_DISCOUNT))
            total += line
        return total
