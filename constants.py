DATA_FILES = [
    "data/target_pool_tv_&_audio.json",
    "data/target_pool_small_appliances.json",
    "data/target_pool_large_appliances.json",
]

# Scraped hidden-retailer files — always indexed with category="scraped"
SCRAPED_FILES = [
    "data/matched_cyberport.json",
    "data/matched_electronic4you.json",
    "data/matched_etec.json",
    "data/matched_expert.json",
]

SCRAPED_CATEGORY = "scraped"

# Maps source file → category string used in target pool
SOURCE_CATEGORY_MAP = {
    "data/source_products_tv_&_audio.json": "TV & Audio",
    "data/source_products_small_appliances.json": "Small Appliances",
    "data/source_products_large_appliances.json": "Large Appliances",
}

QDRANT_URL = "http://localhost:6333"
COLLECTION = "products"
EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIM = 1536
