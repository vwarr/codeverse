import unittest

from cart import Cart


class CartTests(unittest.TestCase):
    def test_add_and_total(self):
        cart = Cart("alice")
        cart.add("apple", 50, 3)
        cart.add("pear", 120)
        self.assertEqual(cart.item_count(), 4)
        self.assertEqual(cart.total_cents(), 270)

    def test_adding_same_sku_merges_lines(self):
        cart = Cart("alice")
        cart.add("apple", 50, 2)
        cart.add("apple", 50, 3)
        self.assertEqual(len(cart.items), 1)
        self.assertEqual(cart.item_count(), 5)

    def test_bulk_discount_applies_at_threshold(self):
        cart = Cart("alice")
        cart.add("bolt", 100, 10)
        self.assertEqual(cart.total_cents(), 900)

    def test_remove(self):
        cart = Cart("alice")
        cart.add("apple", 50)
        cart.add("pear", 120)
        cart.remove("apple")
        self.assertEqual([i.sku for i in cart.items], ["pear"])

    def test_two_customers_have_separate_carts(self):
        alice = Cart("alice")
        bob = Cart("bob")
        alice.add("apple", 50)
        self.assertEqual(bob.item_count(), 0, "bob's new cart already contains alice's items")

    def test_new_cart_is_empty_after_other_carts_were_used(self):
        Cart("carol").add("pear", 120, 2)
        self.assertEqual(Cart("dave").items, [])

    def test_seeding_a_cart_does_not_alias_the_callers_list(self):
        seed = []
        cart = Cart("erin", seed)
        cart.add("apple", 50)
        self.assertEqual(seed, [], "adding to the cart modified the list the caller passed in")

    def test_invalid_quantity(self):
        with self.assertRaises(ValueError):
            Cart("alice").add("apple", 50, 0)


if __name__ == "__main__":
    unittest.main()
