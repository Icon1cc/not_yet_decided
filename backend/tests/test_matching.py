"""
Tests for the product matching service.
"""

import pytest

from backend.app.services.matching import (
    ProductSignals,
    extract_brand,
    extract_eans,
    extract_models,
    extract_product_signals,
    infer_product_kind,
    normalize_text,
    score_product_match,
)


class TestNormalizeText:
    """Tests for text normalization."""

    def test_basic_normalization(self):
        assert normalize_text("Hello World") == "hello world"

    def test_accent_removal(self):
        assert normalize_text("Kühlschrank") == "kuhlschrank"
        assert normalize_text("Geschirr spüler") == "geschirr spuler"

    def test_special_chars(self):
        assert normalize_text("TV & Audio") == "tv and audio"

    def test_none_input(self):
        assert normalize_text(None) == ""


class TestExtractBrand:
    """Tests for brand extraction."""

    def test_from_brand_field(self):
        product = {"brand": "Samsung", "name": "TV 55 inch"}
        assert extract_brand(product) == "SAMSUNG"

    def test_from_name(self):
        product = {"name": "Samsung QE55Q7F QLED TV"}
        assert extract_brand(product) == "SAMSUNG"

    def test_from_specs(self):
        product = {"name": "TV 55 inch", "specifications": {"Marke": "LG"}}
        assert extract_brand(product) == "LG"


class TestExtractEans:
    """Tests for EAN extraction."""

    def test_from_ean_field(self):
        product = {"ean": "8806097123057"}
        assert "8806097123057" in extract_eans(product)

    def test_from_specs(self):
        product = {"specifications": {"GTIN": "8806097123057"}}
        assert "8806097123057" in extract_eans(product)

    def test_invalid_ean(self):
        product = {"ean": "123"}  # Too short
        assert len(extract_eans(product)) == 0


class TestExtractModels:
    """Tests for model number extraction."""

    def test_from_specs(self):
        product = {"specifications": {"Hersteller Modellnummer": "QE55Q7FAAUXXN"}}
        strong, family = extract_models(product)
        assert "QE55Q7FAAUXXN" in strong

    def test_from_name(self):
        product = {"name": "Samsung QE55Q7FAAUXXN QLED TV"}
        strong, family = extract_models(product)
        assert "QE55Q7FAAUXXN" in strong

    def test_filters_blocklist(self):
        product = {"name": "Samsung QLED 4K TV"}
        strong, family = extract_models(product)
        assert "QLED" not in strong
        assert "4K" not in strong


class TestInferProductKind:
    """Tests for product type inference."""

    def test_tv(self):
        product = {"name": "Samsung 55 Zoll Fernseher QLED"}
        assert infer_product_kind(product) == "tv"

    def test_washer(self):
        product = {"name": "Bosch Waschmaschine Serie 6"}
        assert infer_product_kind(product) == "washer"

    def test_dishwasher(self):
        product = {"name": "Siemens Geschirrspüler"}
        assert infer_product_kind(product) == "dishwasher"


class TestScoreProductMatch:
    """Tests for product matching scoring."""

    def test_ean_match(self):
        source = {"name": "Samsung TV", "ean": "8806097123057"}
        target = {"name": "Samsung Television", "ean": "8806097123057"}
        result = score_product_match(source, target)
        assert result.matched
        assert result.score >= 0.99
        assert result.method == "gtin"

    def test_model_match(self):
        source = {
            "name": "Samsung QE55Q7FAAUXXN",
            "specifications": {"Hersteller Modellnummer": "QE55Q7FAAUXXN"},
        }
        target = {
            "name": "Samsung QE55Q7FAAUXXN QLED 4K",
            "specifications": {"Modellnummer": "QE55Q7FAAUXXN"},
        }
        result = score_product_match(source, target)
        assert result.matched
        assert result.score >= 0.90

    def test_brand_conflict(self):
        source = {"name": "Samsung TV 55", "brand": "Samsung"}
        target = {"name": "LG TV 55", "brand": "LG"}
        result = score_product_match(source, target)
        assert not result.matched
        assert result.method == "brand_conflict"

    def test_size_conflict(self):
        source = {"name": "Samsung 55 Zoll TV", "brand": "Samsung"}
        target = {"name": "Samsung 65 Zoll TV", "brand": "Samsung"}
        result = score_product_match(source, target)
        assert not result.matched


class TestExtractProductSignals:
    """Tests for full signal extraction."""

    def test_complete_extraction(self):
        product = {
            "name": "Samsung QE55Q7FAAUXXN QLED 4K TV",
            "brand": "Samsung",
            "ean": "8806097123057",
            "specifications": {"Hersteller Modellnummer": "QE55Q7FAAUXXN"},
        }
        signals = extract_product_signals(product)

        assert signals.brand == "SAMSUNG"
        assert "8806097123057" in signals.eans
        assert "QE55Q7FAAUXXN" in signals.strong_models
        assert signals.kind == "tv"
        assert signals.screen_size_inch == 55.0
