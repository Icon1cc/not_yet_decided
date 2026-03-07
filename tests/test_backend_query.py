import unittest
from pathlib import Path

from backend.matcher_service import matcher


class BackendQueryTests(unittest.TestCase):
    def test_query_returns_submission_shape(self):
        submission, cards, stats = matcher.query(
            query="P_0A7A0D68",
            source_products=None,
            max_sources=5,
            max_competitors_per_source=8,
        )

        self.assertGreaterEqual(len(submission), 1)
        first = submission[0]
        self.assertIn("source_reference", first)
        self.assertIn("competitors", first)
        self.assertIsInstance(first["competitors"], list)

        if first["competitors"]:
            comp = first["competitors"][0]
            self.assertIn("reference", comp)
            self.assertIn("competitor_retailer", comp)
            self.assertIn("competitor_product_name", comp)
            self.assertIn("competitor_url", comp)
            self.assertIn("competitor_price", comp)

        self.assertIn("selected_sources", stats)
        self.assertIn("total_links", stats)
        self.assertIn("kind_filter", stats)
        self.assertIn("target_files_loaded", stats)

    def test_uploaded_source_products_override_default_catalog(self):
        custom_sources = [
            {
                "reference": "P_CUSTOM_1",
                "name": "Custom Product For Backend Test",
                "brand": "CustomBrand",
                "specifications": {},
            }
        ]
        submission, cards, stats = matcher.query(
            query="custom",
            source_products=custom_sources,
            max_sources=5,
            max_competitors_per_source=3,
        )

        self.assertEqual(len(submission), 1)
        self.assertEqual(submission[0]["source_reference"], "P_CUSTOM_1")
        self.assertEqual(stats["selected_sources"], 1)
        self.assertTrue(isinstance(cards, list))

    def test_follow_up_query_uses_history_context(self):
        submission, _, stats = matcher.query(
            query="only under 500 from expert",
            history=["Show Bosch dishwashers"],
            source_products=None,
            max_sources=5,
            max_competitors_per_source=8,
            persist_output=False,
        )

        self.assertIn("bosch", stats["effective_query"].lower())
        self.assertIn("dishwashers", stats["effective_query"].lower())
        self.assertEqual(stats["retailer_filter"], ["Expert AT"])
        self.assertGreaterEqual(len(submission), 1)

    def test_vague_follow_up_reuses_previous_result_set_without_repeating_links(self):
        first_submission, _, first_stats = matcher.query(
            query="show bosch dishwashers",
            history=None,
            source_products=None,
            max_sources=3,
            max_competitors_per_source=6,
            persist_output=False,
        )
        self.assertGreater(first_stats["total_links"], 0)

        second_submission, _, second_stats = matcher.query(
            query="i dont like the results, are there more?",
            history=["show bosch dishwashers"],
            previous_submission=first_submission,
            source_products=None,
            max_sources=3,
            max_competitors_per_source=6,
            persist_output=False,
        )

        first_sources = {row["source_reference"] for row in first_submission}
        second_sources = {row["source_reference"] for row in second_submission}
        self.assertTrue(second_stats["follow_up_expand"])
        self.assertTrue(second_sources.issubset(first_sources))

        shown_keys = set()
        for row in first_submission:
            for competitor in row["competitors"]:
                source_ref = row["source_reference"]
                reference = competitor.get("reference")
                url = competitor.get("competitor_url")
                if reference:
                    shown_keys.add((source_ref, f"ref:{reference}"))
                if url:
                    shown_keys.add((source_ref, f"url:{url.rstrip('/')}"))

        for row in second_submission:
            for competitor in row["competitors"]:
                source_ref = row["source_reference"]
                reference = competitor.get("reference")
                url = competitor.get("competitor_url")
                if reference:
                    self.assertNotIn((source_ref, f"ref:{reference}"), shown_keys)
                if url:
                    self.assertNotIn((source_ref, f"url:{url.rstrip('/')}"), shown_keys)

    def test_microwave_only_query_filters_out_non_microwave_kinds(self):
        submission, _, stats = matcher.query(
            query="show only the microwaves",
            history=None,
            source_products=None,
            max_sources=8,
            max_competitors_per_source=12,
            persist_output=False,
        )

        self.assertIn("microwave", stats["kind_filter"])
        kind_by_ref = {}
        for target in matcher.targets:
            ref = str(target.product.get("reference") or "")
            if ref and ref not in kind_by_ref:
                kind_by_ref[ref] = target.signals.kind

        checked = 0
        for row in submission:
            for competitor in row["competitors"]:
                ref = competitor["reference"]
                kind = kind_by_ref.get(ref)
                if kind is None:
                    continue
                checked += 1
                self.assertEqual(kind, "microwave", msg=f"unexpected kind for {ref}: {kind}")

        self.assertGreater(checked, 0)

    def test_target_files_include_data_pools_and_matched_files(self):
        loaded = {Path(path).name for path in matcher.query(
            query="",
            history=None,
            source_products=None,
            max_sources=1,
            max_competitors_per_source=1,
            persist_output=False,
        )[2]["target_files_loaded"]}

        expected_subset = {
            "target_pool_tv_&_audio.json",
            "target_pool_small_appliances.json",
            "target_pool_large_appliances.json",
            "matched_cyberport.json",
            "matched_electronic4you.json",
            "matched_etec.json",
            "matched_expert.json",
        }
        self.assertTrue(expected_subset.issubset(loaded))

    def test_television_query_maps_to_tv_kind(self):
        _, _, stats = matcher.query(
            query="show only televisions",
            history=None,
            source_products=None,
            max_sources=5,
            max_competitors_per_source=5,
            persist_output=False,
        )
        self.assertIn("tv", stats["kind_filter"])


if __name__ == "__main__":
    unittest.main()
