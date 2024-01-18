"""Activity-based cost-to-serve, with the allocation argument built in.

Every activity-based costing model rests on contestable allocation choices. Is
last-mile cost driven per stop, per parcel, or per kilometre? All three are
defensible, they give different answers, and a model that picks one and
presents the result as fact gets destroyed in the first stakeholder meeting by
somebody who prefers another.

So the drivers are DATA, the model runs under every defensible driver set, and
the output reports which customers change RANK - and, crucially, which change
SIGN. A customer whose profitability flips from positive to negative depending
on an allocation choice is not a costing finding. It is a commercial decision
that has to be made by a human, and saying so is the difference between an
analysis people act on and one they argue about.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# The activity model, expressed as data.
# ---------------------------------------------------------------------------

#: Cost pools and what they total for the period, in GBP. These reconcile to
#: the P&L; allocation cannot create or destroy cost.
COST_POOLS: dict[str, float] = {
    "pickup": 1_850_000.0,
    "sortation": 3_100_000.0,
    "linehaul": 4_400_000.0,
    "last_mile": 9_250_000.0,
    "redelivery": 1_400_000.0,
    "claims": 620_000.0,
    "customer_service": 780_000.0,
}

#: Candidate drivers per pool. Each is a defensible allocation basis, and the
#: disagreement between them is the point rather than a nuisance.
DRIVER_OPTIONS: dict[str, tuple[str, ...]] = {
    "pickup": ("collections", "parcels"),
    "sortation": ("parcels", "weight_kg"),
    "linehaul": ("weight_kg", "parcel_km"),
    "last_mile": ("stops", "parcels", "parcel_km"),
    "redelivery": ("redeliveries", "stops"),
    "claims": ("claims", "parcels"),
    "customer_service": ("cs_contacts", "parcels"),
}

#: Named, defensible driver sets. A reviewer can disagree with any of them and
#: immediately see what their preferred view would imply.
DRIVER_SETS: dict[str, dict[str, str]] = {
    "activity": {
        "pickup": "collections", "sortation": "parcels",
        "linehaul": "parcel_km", "last_mile": "stops",
        "redelivery": "redeliveries", "claims": "claims",
        "customer_service": "cs_contacts",
    },
    "parcel_centric": {
        "pickup": "parcels", "sortation": "parcels",
        "linehaul": "weight_kg", "last_mile": "parcels",
        "redelivery": "stops", "claims": "parcels",
        "customer_service": "parcels",
    },
    "distance_centric": {
        "pickup": "collections", "sortation": "weight_kg",
        "linehaul": "parcel_km", "last_mile": "parcel_km",
        "redelivery": "redeliveries", "claims": "claims",
        "customer_service": "cs_contacts",
    },
}


@dataclass
class Customer:
    id: str
    name: str
    segment: str          # retail_national | ecommerce_sme | rural_specialist
    revenue: float
    parcels: float
    collections: float
    stops: float
    weight_kg: float
    parcel_km: float
    redeliveries: float
    claims: float
    cs_contacts: float

    def driver_value(self, driver: str) -> float:
        return float(getattr(self, driver))


@dataclass(frozen=True)
class Allocation:
    customer_id: str
    by_pool: dict[str, float]
    revenue: float

    @property
    def total_cost(self) -> float:
        return sum(self.by_pool.values())

    @property
    def contribution(self) -> float:
        return self.revenue - self.total_cost

    @property
    def margin_rate(self) -> float:
        return self.contribution / self.revenue if self.revenue else 0.0


def allocate(
    customers: list[Customer], driver_set: dict[str, str],
    pools: dict[str, float] | None = None,
) -> list[Allocation]:
    """Spread every pool across customers in proportion to its driver."""
    pools = pools or COST_POOLS
    totals = {
        pool: sum(c.driver_value(driver) for c in customers)
        for pool, driver in driver_set.items()
    }

    out: list[Allocation] = []
    for c in customers:
        by_pool: dict[str, float] = {}
        for pool, amount in pools.items():
            driver = driver_set[pool]
            total = totals[pool]
            share = c.driver_value(driver) / total if total else 0.0
            by_pool[pool] = amount * share
        out.append(Allocation(c.id, by_pool, c.revenue))
    return out


def leakage(allocations: list[Allocation],
            pools: dict[str, float] | None = None) -> float:
    """Cost that vanished during allocation.

    The single most damaging ABC bug, because it is invisible: a driver that
    is zero for some customers quietly drops their share of the pool, the
    remaining customers look cheaper than they are, and the total no longer
    ties to the P&L that everyone already agreed.
    """
    pools = pools or COST_POOLS
    allocated = sum(a.total_cost for a in allocations)
    return sum(pools.values()) - allocated


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------

@dataclass
class Sensitivity:
    customer_id: str
    name: str
    segment: str
    revenue: float
    contributions: dict[str, float] = field(default_factory=dict)
    ranks: dict[str, int] = field(default_factory=dict)

    @property
    def sign_flips(self) -> bool:
        signs = {c > 0 for c in self.contributions.values()}
        return len(signs) > 1

    @property
    def rank_spread(self) -> int:
        return max(self.ranks.values()) - min(self.ranks.values())

    @property
    def min_contribution(self) -> float:
        return min(self.contributions.values())

    @property
    def max_contribution(self) -> float:
        return max(self.contributions.values())


def sensitivity(
    customers: list[Customer],
    driver_sets: dict[str, dict[str, str]] | None = None,
    pools: dict[str, float] | None = None,
) -> list[Sensitivity]:
    driver_sets = driver_sets or DRIVER_SETS
    pools = pools if pools is not None else scaled_pools(customers)
    by_customer = {
        c.id: Sensitivity(c.id, c.name, c.segment, c.revenue) for c in customers
    }

    for label, driver_set in driver_sets.items():
        allocations = allocate(customers, driver_set, pools)
        ranked = sorted(allocations, key=lambda a: -a.contribution)
        for rank, a in enumerate(ranked, start=1):
            by_customer[a.customer_id].contributions[label] = a.contribution
            by_customer[a.customer_id].ranks[label] = rank

    return sorted(by_customer.values(), key=lambda s: -s.revenue)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

SEGMENTS = {
    # segment -> (parcels/stop, weight/parcel, km/parcel, redeliver rate,
    #             claim rate, cs rate, revenue/parcel)
    "retail_national": (18.0, 2.4, 40.0, 0.02, 0.002, 0.01, 3.05),
    "ecommerce_sme": (3.2, 1.1, 65.0, 0.06, 0.006, 0.05, 4.20),
    "rural_specialist": (1.4, 3.8, 190.0, 0.14, 0.011, 0.09, 5.60),
}


def scaled_pools(
    customers: list[Customer], target_margin: float = 0.14,
) -> dict[str, float]:
    """Scale the cost pools so the business as a whole earns `target_margin`.

    The pool TOTAL is a fact from the P&L; in a fixture it has to be made
    consistent with the revenue the fixture generates. Without this the whole
    population sits at break-even, every customer's contribution is near zero,
    and their ranks churn under any allocation change - which makes the
    sensitivity analysis look like noise rather than a finding.

    The RELATIVE sizes of the pools, which is what allocation actually
    depends on, are untouched.
    """
    revenue = sum(c.revenue for c in customers)
    target_cost = revenue * (1.0 - target_margin)
    current = sum(COST_POOLS.values())
    factor = target_cost / current if current else 1.0
    return {pool: amount * factor for pool, amount in COST_POOLS.items()}


def generate(customers: int = 200, seed: int = 20260911) -> list[Customer]:
    rnd = random.Random(seed)
    out: list[Customer] = []
    names = ("Meridian", "Kestrel", "Halstead", "Brackwater", "Tollgate",
             "Ashcombe", "Penvale", "Rothwell", "Quayside", "Lindmoor")

    for i in range(customers):
        segment = rnd.choices(
            list(SEGMENTS), weights=[0.2, 0.55, 0.25])[0]
        pps, wpp, kpp, redeliver, claim, cs, rev = SEGMENTS[segment]

        parcels = math.exp(rnd.gauss(9.0, 1.1))
        stops = parcels / (pps * rnd.uniform(0.85, 1.15))

        # Negotiated rates vary widely in B2B logistics, and that variation is
        # what separates genuinely profitable accounts from genuinely
        # loss-making ones. With a narrow revenue spread every customer sits
        # near break-even, so their ranks churn under any allocation change and
        # the sensitivity analysis degenerates into "everything is uncertain" -
        # which is exactly as useless as "everything is certain".
        negotiated = rnd.uniform(0.62, 1.45)

        out.append(Customer(
            id=f"CUST{i:04d}",
            name=f"{names[i % len(names)]} {i:03d}",
            segment=segment,
            revenue=parcels * rev * negotiated,
            parcels=parcels,
            collections=max(1.0, stops * rnd.uniform(0.05, 0.12)),
            stops=stops,
            weight_kg=parcels * wpp * rnd.uniform(0.85, 1.15),
            parcel_km=parcels * kpp * rnd.uniform(0.8, 1.25),
            redeliveries=parcels * redeliver * rnd.uniform(0.7, 1.3),
            claims=parcels * claim * rnd.uniform(0.5, 1.6),
            cs_contacts=parcels * cs * rnd.uniform(0.7, 1.4),
        ))
    return out
