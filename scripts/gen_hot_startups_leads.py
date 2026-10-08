"""Write config/leads/hot-startups-2026-10.json: the Paraform Talent Density Index and a list of Dutch startups.

Names and places come from the two public lists (read 2026-10-08). The website is the company's own domain, written
from memory only where the name is unambiguous; a wrong one can only point the resolver at a different site, and the
resolver then reads that site's own careers page, so every board is checked afterwards. Where the name is shared with
other companies no website is given and the lead stays unresolved (the resolver does not guess domains).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PARAFORM_URL = "https://www.paraform.com/talent-density-index"
PARAFORM_LABEL = "paraform_talent_density_index_2026_q4"
NL_LABEL = "linkedin_20_hottest_netherlands_startups_2026_09"

# (rank, name, website or None, headquarters)
PARAFORM = [
    (1, "Safe Superintelligence", "https://ssi.inc", "Palo Alto, US"),
    (2, "Anthropic", "https://www.anthropic.com", "San Francisco, US"),
    (3, "OpenAI", "https://openai.com", "San Francisco, US"),
    (4, "Thinking Machines Lab", "https://thinkingmachines.ai", "San Francisco, US"),
    (5, "Applied Intuition", "https://www.appliedintuition.com", "Mountain View, US"),
    (6, "Modal Labs", "https://modal.com", "New York, US"),
    (7, "Decagon", "https://decagon.ai", "San Francisco, US"),
    (8, "Pika", "https://pika.art", "Palo Alto, US"),
    (9, "Fireworks AI", "https://fireworks.ai", "Redwood City, US"),
    (10, "Cohere", "https://cohere.com", "Toronto, Canada"),
    (11, "Glean", "https://www.glean.com", "Palo Alto, US"),
    (12, "LangChain", "https://www.langchain.com", "San Francisco, US"),
    (13, "Ramp", "https://ramp.com", "New York, US"),
    (14, "Together AI", "https://www.together.ai", "San Francisco, US"),
    (15, "Cognition", "https://cognition.ai", "San Francisco, US"),
    (16, "Harvey", "https://www.harvey.ai", "San Francisco, US"),
    (17, "Scale AI", "https://scale.com", "San Francisco, US"),
    (18, "Perplexity", "https://www.perplexity.ai", "San Francisco, US"),
    (19, "Hebbia", "https://www.hebbia.com", "New York, US"),
    (20, "Rogo", "https://rogo.ai", "New York, US"),
    (21, "Clay", "https://www.clay.com", "New York, US"),
    (22, "Parallel Web Systems", "https://parallel.ai", "San Francisco, US"),
    (23, "Baseten", "https://www.baseten.co", "San Francisco, US"),
    (24, "Anysphere (Cursor)", "https://cursor.com", "San Francisco, US"),
    (25, "Factory", "https://factory.ai", "San Francisco, US"),
    (26, "Linear", "https://linear.app", "San Francisco, US"),
    (27, "Brain Co.", None, "San Francisco, US"),
    (28, "Mercor", "https://mercor.com", "San Francisco, US"),
    (29, "Mistral", "https://mistral.ai", "Paris, France"),
    (30, "Sierra", "https://sierra.ai", "San Francisco, US"),
    (31, "Traversal", "https://traversal.com", "New York, US"),
    (32, "Metronome", "https://metronome.com", "San Francisco, US"),
    (33, "Nuro", "https://www.nuro.ai", "Mountain View, US"),
    (34, "Adept", "https://www.adept.ai", "San Francisco, US"),
    (35, "ElevenLabs", "https://elevenlabs.io", "New York, US"),
    (36, "Runway", "https://runwayml.com", "New York, US"),
    (37, "Vannevar Labs", "https://www.vannevarlabs.com", "Palo Alto, US"),
    (38, "Abridge", "https://www.abridge.com", "San Francisco, US"),
    (39, "HeyGen", "https://www.heygen.com", "Los Angeles, US"),
    (40, "Reevo", "https://www.reevo.ai", "Menlo Park, US"),
    (41, "Chalk", "https://chalk.ai", "San Francisco, US"),
    (42, "Nominal", "https://nominal.io", "Los Angeles, US"),
    (43, "Cartesia", "https://cartesia.ai", "San Francisco, US"),
    (44, "Hex Technologies", "https://hex.tech", "San Francisco, US"),
    (45, "Merge", "https://www.merge.dev", "San Francisco, US"),
    (46, "Whatnot", "https://www.whatnot.com", "Los Angeles, US"),
    (47, "Eventual", None, "San Francisco, US"),
    (48, "Faire", "https://www.faire.com", "San Francisco, US"),
    (49, "Arena", None, "San Francisco, US"),
    (50, "Bedrock Robotics", "https://www.bedrockrobotics.com", "San Francisco, US"),
]

# (name, website or None, place and what the list says)
NETHERLANDS = [
    ("Mews", "https://www.mews.com", "Amsterdam; hospitality software, 32 live roles"),
    ("Framer", "https://www.framer.com", "Amsterdam; website builder, 8 live roles"),
    ("Picnic Technologies", "https://picnic.app", "Amsterdam; online grocery, 230 jobs"),
    ("Catawiki", "https://www.catawiki.com", "Amsterdam; curated marketplace, 46 open roles"),
    ("bunq", "https://www.bunq.com", "Amsterdam; digital bank"),
    ("Mollie", "https://www.mollie.com", "Amsterdam; fintech infrastructure, 42 open roles"),
    ("DataSnipper", "https://www.datasnipper.com", "Amsterdam; AI audit software, 41 open roles"),
    ("QuantWare", "https://www.quantware.com", "Delft; quantum hardware, 27 roles"),
    ("Quatt", "https://quatt.io", "Amsterdam; climate tech, 46+ roles"),
    ("Carbon Equity", None, "Amsterdam; climate investment platform"),
    ("Aquablu", None, "Amsterdam; water tech, 14 openings"),
    ("Solvimon", "https://www.solvimon.com", "Utrecht; fintech software, 3 roles"),
    ("Billy Grace", None, "Amsterdam; marketing analytics, 3 roles"),
    ("Ore Energy", "https://ore.energy", "Amsterdam; long-duration batteries, 4 roles"),
    ("AddOptics", None, "Rotterdam; optical manufacturing, 7 roles"),
    ("THORIZON", None, "Amsterdam and Eindhoven; nuclear deep tech"),
    ("Qualinx B.V.", None, "Delft; semiconductor startup, 8 roles"),
    ("Ditto", None, "Rotterdam; AI doctor consultation summaries, 3 roles"),
    ("Keiron Printing Technologies", None, "Eindhoven; electronics manufacturing, Software Engineer"),
    ("SOUS", None, "Amsterdam; food tech"),
    ("Cradle", "https://www.cradle.bio", "Amsterdam; generative AI for protein design"),
    ("Input", None, "Amsterdam; agentic email system, 5 roles"),
    ("Workwize", "https://www.workwize.com", "Amsterdam; device management"),
]


def lead(name: str, website: str | None, label: str, source_url: str | None, place: str, hint: str, notes: str) -> dict:
    item = {
        "company_name": name,
        "source_type": "web_research",
        "source_label": label,
        "location_hint": place,
        "hiring_hint": hint,
        "notes": notes,
    }
    if website:
        item["website_url"] = website
    if source_url:
        item["source_url"] = source_url
    return item


def build() -> dict:
    leads = [
        lead(
            name, website, PARAFORM_LABEL, PARAFORM_URL, place,
            f"Paraform Talent Density Index 2026 Q4, rank {rank} of 50",
            "Listed by Paraform as a company with a very dense pool of talent (read 2026-10-08). "
            + ("Website written from memory, the resolver reads it." if website
               else "No website given: the name is shared with other companies, so the lead needs one before it can be resolved."),
        )
        for rank, name, website, place in PARAFORM
    ]
    leads += [
        lead(
            name, website, NL_LABEL, None, "Netherlands", hint,
            "From a LinkedIn post of 2026-09-28, '20 hottest Netherlands startups hiring right now'. "
            + ("Website written from memory, the resolver reads it." if website
               else "No website given: it needs one before it can be resolved."),
        )
        for name, website, hint in NETHERLANDS
    ]
    return {"leads": leads}


if __name__ == "__main__":
    target = ROOT / "config" / "leads" / "hot-startups-2026-10.json"
    target.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(build()['leads'])} leads)")
