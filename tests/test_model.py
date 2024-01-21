"""Reconciliation first, then sensitivity. An ABC model that leaks cost is
wrong in a way that is invisible in every report it produces."""

from __future__ import annotations

import unittest

from src.model import (
    COST_POOLS, DRIVER_OPTIONS, DRIVER_SETS, Customer, allocate, generate,
    leakage, sensitivity,
)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.customers = generate(customers=200, seed=20260911)
        cls.sens = sensitivity(cls.customers)


class TestReconciliation(Base):
    def test_silent_leakage_every_driver_set_allocates_100_percent(self):
        for label, driver_set in DRIVER_SETS.items():
            with self.subTest(driver_set=label):
                allocations = allocate(self.customers, driver_set)
                lost = leakage(allocations)
                self.assertLess(
                    abs(lost), 1e-6,
                    f"{label}: GBP {lost:,.2f} of cost vanished during "
                    f"allocation - the total no longer ties to the P&L",
                )

    def test_every_pool_is_fully_distributed(self):
        allocations = allocate(self.customers, DRIVER_SETS["activity"])
        for pool, amount in COST_POOLS.items():
            spread = sum(a.by_pool[pool] for a in allocations)
            self.assertAlmostEqual(spread / amount, 1.0, places=9, msg=pool)

    def test_a_customer_with_no_activity_absorbs_no_cost(self):
        zero = Customer(
            id="ZERO", name="Dormant", segment="ecommerce_sme", revenue=0.0,
            parcels=0.0, collections=0.0, stops=0.0, weight_kg=0.0,
            parcel_km=0.0, redeliveries=0.0, claims=0.0, cs_contacts=0.0,
        )
        allocations = allocate([*self.customers, zero], DRIVER_SETS["activity"])
        dormant = next(a for a in allocations if a.customer_id == "ZERO")
        self.assertAlmostEqual(dormant.total_cost, 0.0, places=9)
        # And the cost it did not absorb went to everyone else, not nowhere.
        self.assertLess(abs(leakage(allocations)), 1e-6)

    def test_allocation_is_traceable_back_to_the_pools(self):
        allocations = allocate(self.customers, DRIVER_SETS["activity"])
        a = allocations[0]
        self.assertEqual(set(a.by_pool), set(COST_POOLS))
        self.assertAlmostEqual(a.total_cost, sum(a.by_pool.values()), places=9)


class TestSensitivity(Base):
    def test_some_customers_flip_sign(self):
        flippers = [s for s in self.sens if s.sign_flips]
        self.assertGreater(
            len(flippers), 0,
            "if no customer changes sign, the driver sets are not materially "
            "different and the sensitivity analysis is decoration",
        )

    def test_a_sign_flip_means_the_answer_is_a_decision_not_a_calculation(self):
        for s in self.sens:
            if not s.sign_flips:
                continue
            self.assertLess(s.min_contribution, 0.0)
            self.assertGreater(s.max_contribution, 0.0)

    def test_rankings_move_between_driver_sets(self):
        moved = [s for s in self.sens if s.rank_spread > 5]
        self.assertGreater(
            len(moved), 5,
            "a single ranked list presented as fact would be indefensible",
        )

    def test_every_customer_is_ranked_under_every_driver_set(self):
        for s in self.sens:
            self.assertEqual(set(s.ranks), set(DRIVER_SETS))
            self.assertEqual(set(s.contributions), set(DRIVER_SETS))

    def test_ranks_are_a_permutation_under_each_driver_set(self):
        n = len(self.sens)
        for label in DRIVER_SETS:
            ranks = sorted(s.ranks[label] for s in self.sens)
            self.assertEqual(ranks, list(range(1, n + 1)))

    def test_stable_customers_are_distinguishable_from_unstable_ones(self):
        # Without this the output is "everything is uncertain", which is as
        # useless as "everything is certain". The threshold is expressed
        # relative to the population - a rank spread of 3 places out of 200 is
        # an arbitrary bar, and almost nothing clears it.
        n = len(self.sens)
        tolerance = max(5, n // 20)   # within 5% of the list
        stable = [
            s for s in self.sens
            if not s.sign_flips and s.rank_spread <= tolerance
        ]
        self.assertGreater(
            len(stable), 10,
            f"only {len(stable)}/{n} customers are robust to the allocation "
            f"choice; if that number is near zero the model is reporting noise",
        )

    def test_the_share_of_contested_customers_is_reported_honestly(self):
        # 45% of accounts having a driver-dependent sign is a finding, not a
        # defect - but it has to be stated rather than buried under a single
        # ranked list.
        contested = sum(1 for s in self.sens if s.sign_flips)
        share = contested / len(self.sens)
        self.assertGreater(share, 0.1)
        self.assertLess(share, 0.9,
                        "if almost every customer flips, the driver sets are "
                        "not comparable and the comparison is meaningless")


class TestFindings(Base):
    def test_high_revenue_accounts_can_be_contribution_negative(self):
        top_by_revenue = sorted(self.sens, key=lambda s: -s.revenue)[:50]
        negative = [
            s for s in top_by_revenue
            if s.contributions["activity"] < 0
        ]
        self.assertGreater(
            len(negative), 0,
            "the whole premise is that revenue rank and profitability rank "
            "are different orderings",
        )

    def test_rural_customers_cost_more_to_serve_under_activity_drivers(self):
        def mean_rate(segment: str) -> float:
            rows = [s for s in self.sens if s.segment == segment]
            return sum(
                s.contributions["activity"] / s.revenue for s in rows) / len(rows)

        self.assertLess(mean_rate("rural_specialist"), mean_rate("retail_national"))

    def test_the_parcel_centric_view_hides_the_rural_cost(self):
        # Allocating last mile per parcel spreads the cost of a one-parcel
        # rural stop across everyone. This is exactly the disagreement the
        # sensitivity analysis exists to expose.
        def mean_rate(segment: str, driver_set: str) -> float:
            rows = [s for s in self.sens if s.segment == segment]
            return sum(
                s.contributions[driver_set] / s.revenue for s in rows) / len(rows)

        activity = mean_rate("rural_specialist", "activity")
        parcel = mean_rate("rural_specialist", "parcel_centric")
        self.assertGreater(parcel, activity,
                           "per-parcel allocation should flatter rural accounts")


class TestModelIsData(Base):
    def test_every_pool_has_at_least_two_defensible_drivers(self):
        for pool in COST_POOLS:
            self.assertIn(pool, DRIVER_OPTIONS)
            self.assertGreaterEqual(len(DRIVER_OPTIONS[pool]), 2)

    def test_every_driver_set_covers_every_pool_with_a_valid_driver(self):
        for label, driver_set in DRIVER_SETS.items():
            with self.subTest(driver_set=label):
                self.assertEqual(set(driver_set), set(COST_POOLS))
                for pool, driver in driver_set.items():
                    self.assertIn(driver, DRIVER_OPTIONS[pool],
                                  f"{label}/{pool}: {driver} is not a declared option")

    def test_a_new_driver_set_needs_no_code_change(self):
        custom = {pool: DRIVER_OPTIONS[pool][-1] for pool in COST_POOLS}
        allocations = allocate(self.customers, custom)
        self.assertLess(abs(leakage(allocations)), 1e-6)


if __name__ == "__main__":
    unittest.main()
