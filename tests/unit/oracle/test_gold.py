from pathlib import Path

from dlens_oracle.gold import Gold, load_gold

SPEC = Path(__file__).parents[3] / "corpora" / "synthetic_shop" / "lineage_spec.yml"


def test_load_gold_expands_indirect_rows_with_d7() -> None:
    gold = load_gold(SPEC)
    assert len(gold.models) == 49 and len(gold.seeds) == 14
    # targets: all on a v1 JOIN key; a pair that already has a direct edge keeps only the direct
    hop = gold.one_hop("stg_products.product_id")
    assert hop["int_order_items_enriched.product_category"] == {"JOIN"}
    assert hop["int_order_items_enriched.product_id"] == {"JOIN"}  # its direct input is items'
    assert gold.labels("stg_order_items.product_id", "int_order_items_enriched.product_id") == {
        "IDENTITY"
    }
    assert ("stg_products.product_id", "int_order_items_enriched", "JOIN") in gold.row_set


def test_closure_direct_vs_indirect_and_drop() -> None:
    gold = Gold(
        seeds={}, models={}, depends_on={},
        direct={("a.x", "b.x"): "IDENTITY", ("b.x", "c.x"): "IDENTITY"},
        indirect={("a.k", "b.x"): {"JOIN"}},
    )  # fmt: skip
    assert gold.closure("a.x", include_indirect=False) == {"b.x", "c.x"}
    assert gold.closure("a.k", include_indirect=False) == set()
    assert gold.closure("a.k", include_indirect=True) == {"b.x", "c.x"}
    assert gold.closure("a.k", include_indirect=True, drop=[("a.k", "b.x")]) == set()
    assert gold.direct_inputs("c.x") == {"b.x"}
