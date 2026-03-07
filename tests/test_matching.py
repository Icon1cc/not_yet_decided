import json
import unittest
from pathlib import Path

from matching_utils import (
    build_deterministic_query_terms,
    clean_specs_for_matching,
    score_product_match,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load_json(name: str):
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)


def find_by_reference(rows: list[dict], reference: str) -> dict:
    return next(row for row in rows if row["reference"] == reference)


def find_by_name(rows: list[dict], needle: str) -> dict:
    needle = needle.lower()
    return next(row for row in rows if needle in (row.get("name") or "").lower())


class MatchingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tv_sources = load_json("source_products_tv_&_audio.json")
        cls.tv_pool = load_json("target_pool_tv_&_audio.json")
        cls.small_sources = load_json("source_products_small_appliances.json")
        cls.small_pool = load_json("target_pool_small_appliances.json")
        cls.large_sources = load_json("source_products_large_appliances.json")
        cls.large_pool = load_json("target_pool_large_appliances.json")

    def test_clean_specs_for_matching_drops_debug_metadata(self):
        specs = {
            "GTIN": "8806097123057",
            "Color": "Black",
            "source_query_model": "QE55Q7FAAUXXN",
            "source_model": "QE55Q7FAAUXXN",
            "_search_query": "site:cyberport.at 8806097123057",
            "_url_slug_name": "samsung qe55q7f",
        }
        cleaned = clean_specs_for_matching(specs)
        self.assertEqual(cleaned, {"GTIN": "8806097123057", "Color": "Black"})

    def test_query_terms_do_not_promote_marketing_tokens_as_models(self):
        source = find_by_reference(self.tv_sources, "P_349C559B")
        terms = build_deterministic_query_terms(source)
        upper_terms = [term.upper() for term in terms]
        self.assertNotIn("HDR10", upper_terms)
        self.assertFalse(any(term.startswith("DVB") for term in upper_terms))
        self.assertTrue(any("XIAOMI" in term for term in upper_terms))

    def test_rejects_cross_size_same_series_tv(self):
        source = find_by_reference(self.tv_sources, "P_0A7A0D68")
        wrong_target = find_by_reference(self.tv_pool, "P_7F413D7D")
        result = score_product_match(source, wrong_target)
        self.assertFalse(result.matched)
        self.assertEqual(result.method, "size_conflict")

    def test_rejects_marketing_token_false_positive(self):
        source = find_by_reference(self.tv_sources, "P_349C559B")
        wrong_target = find_by_name(self.tv_pool, "CHIQ 32QA10")
        result = score_product_match(source, wrong_target)
        self.assertFalse(result.matched)

    def test_rejects_generic_product_line_across_appliance_types(self):
        source = find_by_reference(self.large_sources, "P_01EE21C8")
        wrong_target = find_by_name(self.large_pool, "Siemens ET61RBNA1E")
        result = score_product_match(source, wrong_target)
        self.assertFalse(result.matched)
        self.assertEqual(result.method, "kind_conflict")

    def test_rejects_dirty_gtin_collision(self):
        source = find_by_reference(self.small_sources, "P_F24DB7EA")
        wrong_target = find_by_reference(self.small_pool, "P_7DD0C99E")
        result = score_product_match(source, wrong_target)
        self.assertFalse(result.matched)

    def test_rejects_adjacent_sku_variant(self):
        source = find_by_reference(self.tv_sources, "P_3725B4AD")
        wrong_target = find_by_name(self.tv_pool, "32GF-5024C")
        result = score_product_match(source, wrong_target)
        self.assertFalse(result.matched)
        self.assertEqual(result.method, "model_conflict")

    def test_accepts_exact_model_match(self):
        source = find_by_reference(self.small_sources, "P_06F3C397")
        target = find_by_name(self.small_pool, "PF11257 Mikrowellendeckel Set")
        result = score_product_match(source, target)
        self.assertTrue(result.matched)
        self.assertEqual(result.method, "model")


if __name__ == "__main__":
    unittest.main()
