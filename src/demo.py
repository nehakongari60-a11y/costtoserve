"""The 60-second artefact: which four customers need a commercial decision.

Run: python -m src.demo
"""

from __future__ import annotations

from .model import (
    DRIVER_SETS, allocate, generate, leakage, scaled_pools, sensitivity,
)


def main() -> None:
    customers = generate(customers=200, seed=20260911)
    pools = scaled_pools(customers)
    sens = sensitivity(customers, pools=pools)

    revenue = sum(c.revenue for c in customers)
    print("\n  COSTTOSERVE - the ranked list is not the answer")
    print("  " + "=" * 76)
    print(f"  {len(customers)} customers, GBP {revenue:,.0f} revenue, "
          f"GBP {sum(pools.values()):,.0f} cost to allocate.\n")

    print("  Reconciliation (the check nobody does, and the bug nobody sees):")
    for label, driver_set in DRIVER_SETS.items():
        lost = leakage(allocate(customers, driver_set, pools), pools)
        print(f"    {label:<18} unallocated: GBP {lost:>12,.6f}")
    print("    Cost cannot be created or destroyed by an allocation choice.\n")

    by_revenue = sorted(sens, key=lambda s: -s.revenue)[:50]
    negative = [s for s in by_revenue if s.contributions["activity"] < 0]
    flippers = [s for s in by_revenue if s.sign_flips]

    print("  THE FINDING")
    print("  " + "-" * 76)
    print(f"    {len(negative)} of the top 50 accounts by revenue are")
    print("    contribution-NEGATIVE under activity-based drivers.")
    print(f"    Separately, {len(flippers)} of those top 50 change SIGN")
    print("    depending on which allocation driver you accept.\n")

    print("  Accounts whose profitability depends on an allocation decision:")
    print(f"    {'customer':<18}{'segment':<20}{'revenue':>12}"
          f"{'worst':>12}{'best':>12}")
    print("    " + "-" * 74)
    for s in sorted(flippers, key=lambda x: -x.revenue)[:6]:
        print(f"    {s.name:<18}{s.segment:<20}{s.revenue:>12,.0f}"
              f"{s.min_contribution:>12,.0f}{s.max_contribution:>12,.0f}")

    print("\n    These are not costing findings. Whether last-mile cost is")
    print("    driven per stop or per parcel is a commercial judgement, and")
    print("    until somebody makes it these accounts have no answer.\n")

    contested = sum(1 for s in sens if s.sign_flips)
    tolerance = max(5, len(sens) // 20)
    stable = sum(1 for s in sens if not s.sign_flips and s.rank_spread <= tolerance)
    print("  Robustness across the whole book:")
    print(f"    {stable:>4} accounts are robust to the allocation choice")
    print(f"    {contested:>4} accounts change profitability SIGN "
          f"({contested / len(sens):.0%})")
    print("    A single ranked list would present all 200 with equal confidence.\n")

    print("  Segment view (activity drivers):")
    print(f"    {'segment':<20}{'accounts':>10}{'margin rate':>14}")
    for segment in sorted({s.segment for s in sens}):
        rows = [s for s in sens if s.segment == segment]
        rate = sum(s.contributions["activity"] for s in rows) / sum(
            s.revenue for s in rows)
        print(f"    {segment:<20}{len(rows):>10}{rate:>13.1%}")
    print("\n    Rural delivery costs what it costs. Allocating last-mile per")
    print("    parcel hides that by spreading a one-parcel rural stop across")
    print("    every customer in the book.\n")


if __name__ == "__main__":
    main()
