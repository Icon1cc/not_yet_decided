from retrieval.indexing import product_to_chunk

# ── Match / No-Match ──────────────────────────────────────────────────────────

MATCH_SYSTEM = """You are a product matching expert for an Austrian retailer. Your job is to find competitor listings for the same product — err on the side of MATCH when in doubt.

You receive a SOURCE product and a list of CANDIDATE products from competitor retailers.
For each candidate decide if it is the SAME or EQUIVALENT product as the source, sold by a different retailer.

Rules for MATCH (be generous):
- Same brand + same screen/product size + same model series = MATCH, even if one uses a full regional code and the other a short series name
  * "QE55Q7FAAUXXN" vs "Q7F 55 Zoll" = MATCH (Q7F series, same 55" size)
  * "UE32F6000FUXXN" vs "F6000 32 Zoll" = MATCH
  * "32LQ63806LC" vs "32LQ63806LC" = MATCH
- Color, finish, regional, or year suffix variants = MATCH
  * "PTV 32GF-5025C-B" vs "PTV 32GF-5025C" = MATCH (-B is color variant)
- Minor listing differences OK: extra words, retailer suffix, translated descriptions
- If EAN or GTIN matches = always MATCH
- If unsure but brand + size + product type look right = lean toward MATCH

Rules for NO_MATCH (only clear disqualifiers):
- Definitively different screen size (e.g. 32" vs 40") AND different model = NO_MATCH
- Clearly different model series with no overlap (e.g. Q7F vs Q8F, S5403 vs V5C) = NO_MATCH
- Completely different product type (e.g. TV vs soundbar) = NO_MATCH

Output exactly one line per candidate in this format:
<reference>: MATCH
<reference>: NO_MATCH

No other text. No explanations.
"""


def build_match_prompt(source: dict, candidates: list[dict]) -> str:
    source_chunk = product_to_chunk(source)
    candidate_blocks = []
    for c in candidates:
        chunk = c.get("chunk_text") or product_to_chunk(c)
        candidate_blocks.append(f"CANDIDATE {c['reference']}:\n{chunk}")
    candidates_text = "\n\n".join(candidate_blocks)
    return (
        f"SOURCE PRODUCT:\n{source_chunk}\n\n"
        f"CANDIDATES:\n{candidates_text}\n\n"
        "Output one line per candidate: <reference>: MATCH or <reference>: NO_MATCH\nDo NOT wrap the reference in brackets."
    )


# ── Query Expansion ───────────────────────────────────────────────────────────

EXPANSION_SYSTEM = """You are a product search expert. Given a product, extract up to 8 search terms that uniquely identify it.

Rules:
- Focus on WHAT THE PRODUCT IS, not what it is compatible with or what it includes in the box
- CRITICAL: Ignore all text after "für", "kompatibel mit", "compatible with", "fits", "for use with"
- For accessories (cables, headphones): focus on the accessory itself; NEVER extract phone/TV/console names from compatibility lists
- For TVs: ALWAYS decompose full model codes into their short series name + size:
  * "QE55Q7FAAUXXN" → also emit "Q7F" and "Samsung Q7F 55" (Q7F is the series embedded in the full code)
  * "UE32F6000FUXXN" → also emit "F6000" and "Samsung F6000 32"
  * "32LQ63806LC" → also emit "32LQ63806" and "LQ63806" (strip trailing regional suffix)
  * "55HP6265E" → also emit "HP6265" and "Sharp HP6265 55"
- Include synonyms for generic products (e.g. Mikrowellendeckel → also Mikrowellenhaube)
- Each term must be independently searchable (short phrase or keyword, not a sentence)
- Return one term per line, most discriminative first. No bullets, no numbering, no explanations.

Examples:

INPUT:
Name: SAMSUNG F6000 (2025) 24 Zoll Full HD Smart TV
Specs: Hersteller Modellnummer=UE24F6000FUXXN, GTIN=8806095913957, Bildschirmdiagonale=60 cm / 24 Zoll

OUTPUT:
UE24F6000FUXXN
8806095913957
SAMSUNG F6000 24 Zoll
SAMSUNG F6000 2025
Samsung Full HD Smart TV 24

---

INPUT:
Name: Ziyan In-Ear Kopfhörer + Mikrofon Ohrstöpsel Headset für Huawei Samsung HTC Bass Klang
Specs: (none)

OUTPUT:
Ziyan In-Ear Kopfhörer Mikrofon
Ziyan Headset Ohrstöpsel
In-Ear Kopfhörer Headset Bass

---

INPUT:
Name: 2 Pack USB C Kopfhörer für Samsung Galaxy S24 S23 Ultra S22 S21 S20 A53 A54 USB C Kopfhörer mit Mikrofon In-Ear Kopfhörer mit Kabel Ohrhörer USB Typ C für iPhone 17 16 15 Pro Max, Google Pixel 9, Weiß
Specs: Kopfhörerbuchse=USB-C, Formfaktor=Im Ohr, Konnektivitätstechnologie=Mit Kabel

OUTPUT:
USB C Kopfhörer In-Ear kabelgebunden
USB-C In-Ear Kopfhörer mit Mikrofon Weiß
USB Typ C Ohrhörer kabelgebunden Weiß

---

INPUT:
Name: sonero Stromkabel Netzkabel 2 Polig, 1,50m, Eurostecker Typ C Netzstecker auf IEC Buchse C7 Euro 8 Stecker, Netzteil Strom Kabel für TV, PS5, PS4, PS3, Haushaltsgeräte, Schwarz
Specs: (none)

OUTPUT:
sonero Netzkabel 2 Polig 1.5m
sonero Eurostecker C7 Stromkabel Schwarz
Netzkabel 2 polig Eurostecker C7 1.5m schwarz
Stromkabel IEC C7 Eurostecker 1.5m

---

INPUT:
Name: Ancable 3M Netzkabel Stromkabel 2 polig, C7 Kabel Eurostecker Stromkabel 90° Euro Netzkabel für Samsung Fernseher LG Philips Sony Panasonic TV PS5 PS4 Xbox PC Kleingerätekabel - Weiß
Specs: (none)

OUTPUT:
Ancable Netzkabel 2 polig C7 3m Weiß
Ancable Eurostecker C7 90° Stromkabel
Netzkabel 2 polig C7 3m 90 Grad gewinkelt weiß

---

INPUT:
Name: JBL Wave 200 TWS True-Wireless In-Ear Bluetooth-Kopfhörer - Weiß – Kabellose Ohrhörer mit integriertem Mikrofon – Musik Streaming bis zu 20 Stunden – Inkl. Ladecase
Specs: (none)

OUTPUT:
JBL Wave 200 TWS
JBL Wave 200
JBL Wave 200 Bluetooth Kopfhörer Weiß
JBL TWS In-Ear Weiß

---

INPUT:
Name: meberg PF11257 Mikrowellendeckel Glockenform 25 cm BPA frei Kunststoff Mikrowellenabdeckhaube Mikrowellenhaube
Specs: Größe=25 cm, Material=Kunststoff, BPA-frei=Ja

OUTPUT:
meberg PF11257
meberg Mikrowellendeckel 25 cm
Mikrowellendeckel Glockenform 25 cm BPA frei
Mikrowellenhaube 25 cm Kunststoff
Mikrowellenabdeckung 25 cm

---

INPUT:
Name: REMINGTON S6505 Proo Sleek & Curl Haarglätter (Keramik, Temperaturstufen: 10, Violett)
Specs: Hersteller Modellnummer=S6505, Marke=Remington

OUTPUT:
REMINGTON S6505
Remington S6505 Haarglätter
Remington Sleek Curl Haarglätter Keramik Violett
Remington Haarglätter S6505 Keramik

---

INPUT:
Name: ROMMELSBACHER Vakuumierer VAC 585, Absaugleistung 20 Liter/Min., Einhand-Bedienung, Langzeitbetrieb geeignet, Doppel-Versiegelungsnaht, 2 Programme, 2 Geschwindigkeiten, für Folien bis 30 cm
Specs: Marke=Rommelsbacher, Modellnummer=VAC 585

OUTPUT:
ROMMELSBACHER VAC 585
Rommelsbacher Vakuumierer VAC585
Rommelsbacher Vakuumierer 20 Liter
Vakuumierer Doppel-Versiegelungsnaht 30 cm
"""


def build_expansion_prompt(source: dict) -> str:
    name = source.get("name") or ""
    specs = source.get("specifications") or {}

    # enrichment fields (present after enrich_products())
    enrichment_parts = []
    if source.get("model_number"):
        enrichment_parts.append(f"Model number={source['model_number']}")
    if source.get("brand_norm"):
        enrichment_parts.append(f"Brand={source['brand_norm']}")
    if source.get("size") is not None:
        unit = source.get("size_unit") or ""
        enrichment_parts.append(f"Size={source['size']} {unit}".strip())
    if source.get("resolution"):
        enrichment_parts.append(f"Resolution={source['resolution']}")
    if source.get("product_type"):
        enrichment_parts.append(f"Type={source['product_type']}")

    # high-signal spec fields
    key_specs = {k: v for k, v in specs.items() if v and k in (
        "GTIN", "EAN", "EAN-Code",
        "Hersteller Modellnummer", "Hersteller Artikelnummer", "Herstellernummer",
        "Modellnummer", "Modellname", "Artikelnummer",
        "Marke", "Hersteller",
        "Größe", "Bildschirmdiagonale (cm/Zoll)", "Bildschirmdiagonale in cm, Zoll",
        "Kopfhörerbuchse", "Formfaktor", "Konnektivitätstechnologie",
        "Farbe", "Farbe (laut Hersteller)", "Material",
    )}
    ean = source.get("ean")
    if ean:
        key_specs = {"EAN": ean, **key_specs}

    specs_str = ", ".join(f"{k}={v}" for k, v in key_specs.items()) if key_specs else "(none)"
    enrichment_str = ", ".join(enrichment_parts)

    prompt = f"Name: {name}\nSpecs: {specs_str}"
    if enrichment_str:
        prompt += f"\nEnrichment: {enrichment_str}"
    return prompt
