#!/usr/bin/env python3
"""Generate a labeled, dimension-covered corpus of synthetic funding documents.

Built on the "dimensions -> tuples -> generate" method from Hamel Husain &
Shreya Shankar's evals work (https://hamel.dev/blog/posts/evals-faq/): define
explicit facets, enumerate combinations for systematic coverage instead of the
model's default mode, then expand each tuple into a full example.

DIMENSIONS
    authorship        human | ai_clean | ai_laundered | slop  (the primary label)
    document_type     grant_application | blog_post | think_tank_report
    institution_tier  R1 | R2 (Carnegie research tiers -- "R1/R2"); flavor
                      resources, framing, and typical award scale. --tiers.
    discipline        biomedical | engineering | social_science | public_health
                      | physical_science
    applicant_type    early_stage_investigator | established_pi | multi_pi_team
                      | small_nonprofit
    defect            (slop only) fabricated_citations | wrong_paper | overclaims
                      | all, plus budget_inflated | budget_math | missing_methods
                      (grants only). wrong_paper = a real, resolving DOI cited as
                      the wrong paper; budget_math = line items that don't sum.

SEED PULLS
    Human grant seeds come from *multiple* NIH RePORTER pulls -- one per Carnegie
    tier, filtered to a starter roster of R1 vs R2 awardee institutions. Human
    blog/report docs and every generated doc are fabricated. --offline fabricates
    everything (no network, nothing real, fully committable).

BACKENDS
    template   stdlib-only, offline, deterministic with --seed. Runs anywhere.
    anthropic  Messages API over urllib (no SDK) when ANTHROPIC_API_KEY is set;
               the full dimension tuple is passed into the prompt (the flashcards
               "tuple -> natural language" step). Falls back to template on error.

OUTPUT (snake_case keys)
    corpus.jsonl    full records, each carrying its dimension tuple + ground_truth
    manifest.csv    one row per doc, dimension + ground-truth columns
    coverage.json   value counts per dimension and tuple coverage (per the guide)
    run_meta.json   run parameters

Examples
--------
    python3 synth_proposals.py --n 240
    python3 synth_proposals.py --n 240 --doctypes grant_application blog_post
    python3 synth_proposals.py --n 240 --offline --seed 7
    python3 synth_proposals.py --n 400 --backend anthropic --model claude-sonnet-5
"""

import argparse
import csv
import itertools
import json
import os
import random
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

NIH_SEARCH_URL = "https://api.reporter.nih.gov/v2/projects/search"

# --------------------------------------------------------------------------- #
# Dimensions
# --------------------------------------------------------------------------- #
AUTHORSHIP = ["human", "ai_clean", "ai_laundered", "slop"]
DOCUMENT_TYPES = ["grant_application", "blog_post", "think_tank_report"]
DISCIPLINES = ["biomedical", "engineering", "social_science", "public_health", "physical_science"]
APPLICANT_TYPES = ["early_stage_investigator", "established_pi", "multi_pi_team", "small_nonprofit"]

# Which slop defects are meaningful for which document type. Budget and methods
# are grant-specific; fabricated citations and overclaims apply everywhere.
GRANT_DEFECTS = [
    "fabricated_citations",
    "wrong_paper",
    "overclaims",
    "budget_inflated",
    "budget_math",
    "missing_methods",
    "all",
]
TEXT_DEFECTS = ["fabricated_citations", "wrong_paper", "overclaims", "all"]
DEFECTS_BY_DOCTYPE = {
    "grant_application": GRANT_DEFECTS,
    "blog_post": TEXT_DEFECTS,
    "think_tank_report": TEXT_DEFECTS,
}

CITATION_HEADING = {
    "grant_application": "References",
    "blog_post": "Sources",
    "think_tank_report": "Endnotes",
}

# Carnegie institution-tier specs -- flavor resources, framing, and award scale.
TIER_SPECS = {
    "R1": {
        "budget_per_year": (250_000, 500_000),
        "years": (3, 5),
        "infrastructure": "extensive core facilities and shared instrumentation",
        "track_record": "a deep institutional record of federally funded work",
    },
    "R2": {
        "budget_per_year": (150_000, 300_000),
        "years": (2, 4),
        "infrastructure": "focused departmental resources and regional research partnerships",
        "track_record": "a growing institutional research base",
    },
}
DEFAULT_TIER = {
    "budget_per_year": (175_000, 400_000),
    "years": (2, 5),
    "infrastructure": "available institutional resources",
    "track_record": "an institutional research record",
}

# Starter rosters used to stratify the NIH pulls by tier. Carnegie tiers shift by
# classification year -- edit these to match the roster the team wants to target.
ORG_LISTS = {
    "R1": [
        "Harvard University",
        "Stanford University",
        "Massachusetts Institute of Technology",
        "University of California, Berkeley",
        "University of Michigan at Ann Arbor",
        "University of Washington",
        "Johns Hopkins University",
        "University of Wisconsin-Madison",
        "Yale University",
        "Columbia University",
        "University of California-Los Angeles",
        "University of Texas at Austin",
        "University of Pennsylvania",
        "University of Minnesota",
        "Duke University",
    ],
    "R2": [
        "Illinois State University",
        "University of Rhode Island",
        "Montana State University",
        "Old Dominion University",
        "Wright State University",
        "Kent State University",
        "University of Northern Colorado",
        "Bowling Green State University",
        "San Diego State University",
        "Texas Woman's University",
        "Idaho State University",
        "Ball State University",
        "Clark University",
        "University of Southern Mississippi",
        "Northern Arizona University",
    ],
}

# Discipline-flavored phrasing, keyed for both generation and seed inference.
DISCIPLINE_FLAVOR = {
    "biomedical": ["mechanistic", "clinical cohort", "biomarker", "in vivo", "translational"],
    "engineering": [
        "prototype",
        "system architecture",
        "throughput",
        "fabrication",
        "control loop",
    ],
    "social_science": [
        "survey instrument",
        "causal identification",
        "population",
        "field experiment",
        "policy",
    ],
    "public_health": ["community", "disparities", "surveillance", "intervention", "screening"],
    "physical_science": ["spectroscopy", "simulation", "materials", "quantum", "characterization"],
}

REAL_DOIS = [
    "10.1038/s41586-020-2649-2",
    "10.1126/science.1259855",
    "10.1016/j.cell.2016.07.054",
    "10.1073/pnas.1517384113",
    "10.1093/nar/gky1055",
    "10.1001/jama.2016.9797",
    "10.1056/NEJMoa2034577",
    "10.1371/journal.pone.0173664",
    "10.1109/TPAMI.2016.2577031",
    "10.1038/nature14539",
    "10.1145/3292500.3330701",
    "10.1101/gr.229102",
    "10.1002/anie.201907688",
    "10.1021/jacs.9b02765",
    "10.1289/ehp.1104477",
]

BUILTIN_TOPICS = {
    "biomedical": [
        "early detection of pancreatic cancer using circulating tumor DNA",
        "gene therapy vectors for inherited retinal degeneration",
        "gut microbiome modulation of neurodegenerative disease progression",
    ],
    "engineering": [
        "wearable sensors for continuous glucose monitoring in rural clinics",
        "energy-efficient edge inference for implantable devices",
        "scalable desalination membranes for arid regions",
    ],
    "social_science": [
        "behavioral economics of retirement savings among gig workers",
        "workforce pathways into the semiconductor manufacturing sector",
        "measuring the labor-market effects of remote work policy",
    ],
    "public_health": [
        "community-based interventions to reduce childhood asthma disparities",
        "wastewater surveillance for early outbreak detection in cities",
        "screening pathways for hypertension in underserved populations",
    ],
    "physical_science": [
        "resilience of coastal wetlands under accelerating climate change",
        "machine learning for protein structure prediction in drug discovery",
        "room-temperature quantum sensing for magnetic imaging",
    ],
}

# Grant-flavored clean/overclaim pools.
CLEAN_SENTENCES = [
    "This proposal addresses {topic}, a problem with substantial significance.",
    "Prior work has established a partial understanding, yet key gaps remain.",
    "Our preliminary data suggest a tractable path toward measurable improvement.",
    "We will assemble a multidisciplinary team with complementary expertise.",
    "The approach integrates established {flavor} methods with a novel analytical pipeline.",
    "Rigorous, pre-registered analyses will guard against bias and support reproducibility.",
    "Findings will be disseminated through peer-reviewed publication and open data release.",
]

OVERCLAIM_SENTENCES = [
    "This work will definitively cure the condition within the funding period.",
    "Our method is guaranteed to outperform every existing approach by an order of magnitude.",
    "Success is certain; there are no meaningful risks or limitations to this plan.",
    "The results will immediately transform practice nationwide upon completion.",
]

# Prose pools for blog posts and reports (no grant vocabulary).
TEXT_CLEAN = [
    "This piece examines {topic}, a question of growing public interest.",
    "The evidence base is partial, and important gaps remain.",
    "Recent analysis points toward a tractable path forward.",
    "Practitioners and policymakers alike have a role to play here.",
    "The discussion draws on established {flavor} methods and current data.",
    "Careful framing guards against overstatement.",
    "The takeaways are meant to inform, not to prescribe.",
]

TEXT_OVERCLAIM = [
    "This is, without question, the definitive account of the issue.",
    "The conclusions here are beyond dispute and settle the debate for good.",
    "Every serious observer already agrees; the matter is entirely settled.",
    "These findings will transform policy overnight, guaranteed.",
]

APPLICANT_FLAVOR = {
    "early_stage_investigator": "The PI's first independent award; strong mentorship is in place.",
    "established_pi": "The PI has a sustained track record of funded work in this area.",
    "multi_pi_team": "Two co-equal PIs contribute complementary methods under joint leadership.",
    "small_nonprofit": "The applicant is a community nonprofit partnering with an academic core.",
}

TITLE_TEMPLATES = [
    "{cap}",
    "{cap}: A Multidisciplinary Research Program",
    "Advancing {topic}",
    "Toward {topic}",
    "{cap}: Mechanisms and Interventions",
]
BLOG_TITLES = [
    "{cap}: What the Evidence Shows",
    "Why {topic} Matters Now",
    "{cap}, Explained",
    "The Case for Rethinking {topic}",
]
REPORT_TITLES = [
    "{cap}: Findings and Recommendations",
    "A Policy Assessment of {topic}",
    "{cap}: Evidence and Options",
]


@dataclass
class Citation:
    marker: str
    doi: str
    resolves: bool
    claim: str
    # metadata_match is False for the "wrong paper" case: the DOI resolves, but
    # to a different paper than the one cited (cited_source names the claimed one).
    metadata_match: bool = True
    cited_source: str = ""


@dataclass
class Record:
    id: str
    label: str
    dimensions: dict
    title: str
    topic: str
    sections: dict
    text: str
    citations: list
    ground_truth: dict
    provenance: dict
    meta: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Seed pulls (multiple, one per Carnegie tier)
# --------------------------------------------------------------------------- #
def fetch_nih_pull(tier, n, rng):
    criteria = {"fiscal_years": [2021, 2022, 2023]}
    org_names = ORG_LISTS.get(tier)
    if org_names:
        criteria["org_names"] = org_names
    payload = {
        "criteria": criteria,
        "include_fields": ["ProjectTitle", "AbstractText", "ApplId", "OrgName"],
        "limit": min(max(n, 25), 500),
        "offset": rng.randint(0, 150),
    }
    req = urllib.request.Request(
        NIH_SEARCH_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "slopchecker-synth/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        results = json.load(resp).get("results", [])
    seeds = []
    for r in results:
        abstract = (r.get("abstract_text") or "").strip()
        title = (r.get("project_title") or "").strip()
        if len(abstract) > 400:
            seeds.append(
                {
                    "seed_id": str(r.get("appl_id")),
                    "title": title,
                    "abstract": abstract,
                    "seed_source": "nih_reporter",
                    "institution_tier": tier,
                    "org_name": r.get("org_name"),
                    "discipline": _infer_discipline(abstract),
                }
            )
    return seeds


def builtin_seeds(tiers, n_each, rng):
    seeds = []
    for tier in tiers:
        for i in range(n_each):
            disc = rng.choice(DISCIPLINES)
            topic = rng.choice(BUILTIN_TOPICS[disc])
            seeds.append(
                {
                    "seed_id": f"builtin_{tier}_{i:04d}",
                    "title": f"A Program of Research on {topic.capitalize()}",
                    "abstract": _fabricated_abstract(topic, disc, rng),
                    "seed_source": "builtin",
                    "institution_tier": tier,
                    "org_name": None,
                    "discipline": disc,
                }
            )
    return seeds


def collect_seeds(tiers, n_each, offline, rng):
    """Multiple pulls -- one bucket per Carnegie tier. Returns {tier: [seeds]}."""
    buckets = {}
    for tier in tiers:
        if offline:
            buckets[tier] = builtin_seeds([tier], n_each, rng)
            continue
        try:
            pull = fetch_nih_pull(tier, n_each, rng)
            if len(pull) < max(3, n_each // 4):
                pull += builtin_seeds([tier], n_each - len(pull), rng)
            buckets[tier] = pull
            print(f"[pull] {tier}: {len(pull)} seeds")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
            print(f"[warn] NIH pull for {tier} failed ({e}); using built-in seeds")
            buckets[tier] = builtin_seeds([tier], n_each, rng)
    return buckets


def _infer_discipline(text):
    low = text.lower()
    best, score = "biomedical", 0
    for disc, kws in DISCIPLINE_FLAVOR.items():
        s = sum(low.count(k.split()[0]) for k in kws)
        if s > score:
            best, score = disc, s
    return best


def _fabricated_abstract(topic, disc, rng):
    flavor = rng.choice(DISCIPLINE_FLAVOR[disc])
    return " ".join(s.format(topic=topic, flavor=flavor) for s in rng.sample(CLEAN_SENTENCES, k=5))


# --------------------------------------------------------------------------- #
# Anthropic backend (optional, urllib only)
# --------------------------------------------------------------------------- #
def generate_with_anthropic(dims, topic, model):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    spec = _prompt_for(dims, topic)
    if dims["authorship"] == "slop":
        spec += _slop_inject(dims["document_type"], dims["defect"])
    return _post_anthropic(key, model, spec)


def _prompt_for(dims, topic):
    dt = dims["document_type"]
    if dt == "blog_post":
        return (
            "Write a realistic ~350-word policy blog post on the topic below. "
            "Include a one-line dek, a short intro, two or three body paragraphs, "
            "and a takeaway. Conversational but credible. Do not include a title "
            f"or top-level heading. Stay strictly on the topic.\nTopic: {topic}\n"
        )
    if dt == "think_tank_report":
        return (
            "Write a realistic ~350-word think-tank report excerpt on the topic "
            "below. Include Executive Summary, Background, Findings, and "
            "Recommendations sections. Formal and evidence-based. Do not include a "
            f"title or top-level heading. Stay strictly on the topic.\nTopic: {topic}\n"
        )
    tier = dims["institution_tier"]
    tspec = _tier_spec(tier)
    return (
        "Write a realistic ~350-word research grant proposal excerpt (Specific "
        "Aims, Background, Approach, Innovation, Budget Justification).\n"
        f"Topic: {topic}\nInstitution tier: {tier} (Carnegie; {tspec['infrastructure']})\n"
        f"Discipline: {dims['discipline']}\nApplicant: {dims['applicant_type']}\n"
        "Do not include a title or top-level heading; start at the Specific Aims "
        "section. Stay strictly on the stated topic.\n"
    )


def _slop_inject(dt, defect):
    wrong_paper = "cite real, resolvable DOIs but attribute them to the wrong paper/authors"
    if dt == "grant_application":
        inject = {
            "fabricated_citations": "cite sources that sound real but are fabricated",
            "wrong_paper": wrong_paper,
            "overclaims": "include grandiose, unsupported guarantees of success",
            "budget_inflated": "request an implausibly large budget for the scope",
            "budget_math": "itemize a budget whose line items do not sum to the stated total",
            "missing_methods": "keep the methods vague and hand-wavy",
            "all": "do all of: fake citations, wrong-paper citations, overclaims, padded budget",
        }
    else:
        inject = {
            "fabricated_citations": "cite sources that sound real but are fabricated",
            "wrong_paper": wrong_paper,
            "overclaims": "state sweeping, unsupported claims as settled fact",
            "all": "do all of: fabricated sources, wrong-paper citations, unsupported claims",
        }
    return f"Make it subtly low-quality: {inject.get(defect, inject['all'])}."


def _post_anthropic(key, model, prompt):
    payload = {
        "model": model,
        "max_tokens": 1200,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.load(resp)
        return "".join(b.get("text", "") for b in body.get("content", [])).strip()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Document construction
# --------------------------------------------------------------------------- #
def _defect_flags(dims):
    d = dims.get("defect", "none")
    is_all = d == "all"
    grant = dims["document_type"] == "grant_application"
    return {
        "ai_generated": dims["authorship"] != "human",
        "laundered": dims["authorship"] == "ai_laundered",
        "has_fabricated_citations": d == "fabricated_citations" or is_all,
        "has_mismatched_citations": d == "wrong_paper" or is_all,
        "overclaims": d == "overclaims" or is_all,
        "budget_inflated": (d == "budget_inflated" or is_all) and grant,
        "budget_math": (d == "budget_math" or is_all) and grant,
        "missing_methods": (d == "missing_methods" or is_all) and grant,
        # Set only on near-duplicate clones (see add_near_duplicates); a relational
        # property, not derivable from this record's own dimensions.
        "is_near_duplicate": False,
    }


def _make_citations(rng, n, fabricate, mismatch=False):
    cites = []
    for i in range(n):
        roll = rng.random()
        # Three failure modes, mixed per citation:
        #   broken       DOI does not resolve (fabricated_citations)
        #   wrong_paper  DOI resolves, but to a different paper than cited
        #   clean        DOI resolves and matches the cited source
        if fabricate and roll < 0.5:
            doi, resolves, meta_ok = (
                f"10.{rng.randint(1000, 9999)}/{_rand_token(rng)}",
                False,
                False,
            )
            cited = ""
        elif mismatch and roll < (0.5 if not fabricate else 0.8):
            doi, resolves, meta_ok = rng.choice(REAL_DOIS), True, False
            cited = _fake_source(rng)  # what the doc claims the DOI is
        else:
            doi, resolves, meta_ok = rng.choice(REAL_DOIS), True, True
            cited = ""
        cites.append(
            Citation(
                marker=f"[{i + 1}]",
                doi=doi,
                resolves=resolves,
                claim=rng.choice(CLEAN_SENTENCES).format(topic="the target problem", flavor="core"),
                metadata_match=meta_ok,
                cited_source=cited,
            )
        )
    return cites


def _fake_source(rng):
    author = rng.choice(["Nguyen", "Okafor", "Petrova", "Alvarez", "Kim", "Rossi"])
    year = rng.randint(2016, 2024)
    venue = rng.choice(["J. of Applied Analysis", "Nature Communications", "PNAS", "Cell Reports"])
    return f"{author} et al. ({year}), {venue}"


def _rand_token(rng):
    return "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(8))


def _tier_spec(tier):
    return TIER_SPECS.get(tier, DEFAULT_TIER)


def _sections_for(topic, dims, rng):
    dt = dims["document_type"]
    if dt == "blog_post":
        return _blog_sections(topic, dims, rng)
    if dt == "think_tank_report":
        return _report_sections(topic, dims, rng)
    return _grant_sections(topic, dims, rng)


def _grant_sections(topic, dims, rng):
    tier = dims["institution_tier"]
    tspec = _tier_spec(tier)
    flavor = rng.choice(DISCIPLINE_FLAVOR[dims["discipline"]])
    gt = _defect_flags(dims)

    aims = "\n".join(
        f"Aim {i + 1}: Advance {topic} via a {flavor}-focused strategy."
        for i in range(rng.randint(2, 3))
    )
    background = " ".join(
        s.format(topic=topic, flavor=flavor) for s in rng.sample(CLEAN_SENTENCES, k=4)
    )
    if gt["missing_methods"]:
        approach = "We will use appropriate methods to achieve the aims."
    else:
        approach = " ".join(
            s.format(topic=topic, flavor=flavor) for s in rng.sample(CLEAN_SENTENCES, k=4)
        )
    innovation = (
        " ".join(rng.sample(OVERCLAIM_SENTENCES, k=2))
        if gt["overclaims"]
        else rng.choice(CLEAN_SENTENCES).format(topic=topic, flavor=flavor)
    )
    budget = _budget_text(tier, rng, inflated=gt["budget_inflated"], error=gt["budget_math"])
    context = (
        f"{APPLICANT_FLAVOR[dims['applicant_type']]} The {tier} host institution offers "
        f"{tspec['infrastructure']}, backed by {tspec['track_record']}."
    )
    return {
        "specific_aims": aims,
        "background": background,
        "approach": approach,
        "innovation": innovation,
        "investigator_context": context,
        "budget_justification": budget,
    }


def _blog_sections(topic, dims, rng):
    flavor = rng.choice(DISCIPLINE_FLAVOR[dims["discipline"]])
    gt = _defect_flags(dims)
    intro = " ".join(s.format(topic=topic, flavor=flavor) for s in rng.sample(TEXT_CLEAN, k=3))
    body = " ".join(s.format(topic=topic, flavor=flavor) for s in rng.sample(TEXT_CLEAN, k=3))
    if gt["overclaims"]:
        takeaway = " ".join(rng.sample(TEXT_OVERCLAIM, k=2))
    else:
        takeaway = rng.choice(TEXT_CLEAN).format(topic=topic, flavor=flavor)
    return {
        "dek": f"What we know about {topic}, and what to watch.",
        "intro": intro,
        "body": body,
        "takeaway": takeaway,
    }


def _report_sections(topic, dims, rng):
    flavor = rng.choice(DISCIPLINE_FLAVOR[dims["discipline"]])
    gt = _defect_flags(dims)
    exec_summary = " ".join(
        s.format(topic=topic, flavor=flavor) for s in rng.sample(TEXT_CLEAN, k=2)
    )
    background = " ".join(s.format(topic=topic, flavor=flavor) for s in rng.sample(TEXT_CLEAN, k=3))
    findings_base = " ".join(
        s.format(topic=topic, flavor=flavor) for s in rng.sample(TEXT_CLEAN, k=3)
    )
    findings = (
        (rng.choice(TEXT_OVERCLAIM) + " " + findings_base) if gt["overclaims"] else findings_base
    )
    recommendations = " ".join(
        s.format(topic=topic, flavor=flavor) for s in rng.sample(TEXT_CLEAN, k=2)
    )
    return {
        "executive_summary": exec_summary,
        "background": background,
        "findings": findings,
        "recommendations": recommendations,
    }


def _budget_text(tier, rng, inflated, error=False):
    tspec = _tier_spec(tier)
    lo, hi = tspec["budget_per_year"]
    years = rng.randint(*tspec["years"])
    mult = rng.randint(4, 8) if inflated else 1
    personnel = rng.randint(lo, hi) * years * mult // 2
    equipment = rng.randint(20_000, 120_000) * mult
    travel = rng.randint(5_000, 25_000) * mult
    indirect = rng.randint(30_000, 150_000) * mult
    items_sum = personnel + equipment + travel + indirect
    # budget_math: the stated total does not equal the sum of the line items.
    stated = items_sum + rng.choice([-1, 1]) * rng.randint(10_000, 90_000) if error else items_sum
    return (
        f"Budget: personnel ${personnel:,}; equipment ${equipment:,}; "
        f"travel ${travel:,}; indirect costs ${indirect:,}. "
        f"Total requested support is ${stated:,} over {years} years at a {tier} institution."
    )


def _launder(text, rng):
    swaps = {
        "This proposal addresses": "The present application concerns",
        "This piece examines": "The present article considers",
        "Our preliminary data suggest": "Pilot findings indicate",
        "We will": "The team intends to",
        "novel": "innovative",
        "substantial": "considerable",
        "rigorous": "carefully controlled",
    }
    for a, b in swaps.items():
        text = text.replace(a, b)
    sents = re.split(r"(?<=[.!?])\s+", text)
    rng.shuffle(sents)
    return " ".join(sents)


def build_record(idx, dims, seed, backend, model, rng):
    dt = dims["document_type"]
    gt = _defect_flags(dims)
    used_model = None

    if dims["authorship"] == "human":
        if dt == "grant_application" and seed.get("seed_source") == "nih_reporter":
            topic = _clean_title(seed.get("title", ""))
            title = seed["title"]
            sections = {"abstract": seed["abstract"]}
            cites = _make_citations(rng, rng.randint(3, 8), fabricate=False)
            full = _assemble(title, sections, cites, dt, human_text=seed["abstract"])
        else:
            topic = rng.choice(BUILTIN_TOPICS[dims["discipline"]])
            title = _title_for(topic, dims, rng)
            sections = _sections_for(topic, dims, rng)  # defect none -> clean
            cites = _make_citations(rng, rng.randint(3, 8), fabricate=False)
            full = _assemble(title, sections, cites, dt, human_text=None)
    else:
        topic = rng.choice(BUILTIN_TOPICS[dims["discipline"]])
        title = _title_for(topic, dims, rng)  # keep title and body on the same topic
        sections, body, used_model = _generate_body(topic, dims, backend, model, rng)
        if dims["authorship"] == "ai_laundered":
            body = _launder(body, rng)
        cites = _make_citations(
            rng,
            rng.randint(4, 10),
            fabricate=gt["has_fabricated_citations"],
            mismatch=gt["has_mismatched_citations"],
        )
        full = _assemble(title, sections, cites, dt, human_text=None, override_body=body)

    n_unresolvable = sum(1 for c in cites if not c.resolves)
    n_mismatched = sum(1 for c in cites if c.resolves and not c.metadata_match)
    prov = {
        "backend": backend if used_model else "template",
        "seed_source": seed["seed_source"],
        "seed_id": seed["seed_id"],
        "model": used_model,
    }
    meta = {
        "requested_budget_usd": _extract_budget(sections),
        "n_citations": len(cites),
        "n_unresolvable_citations": n_unresolvable,
        "n_mismatched_citations": n_mismatched,
        "duplicate_of": None,  # set on near-duplicate clones
    }
    return Record(
        id=f"synth_{idx:05d}",
        label=dims["authorship"],
        dimensions=dict(dims),
        title=title,
        topic=topic,
        sections=sections,
        text=full,
        citations=[asdict(c) for c in cites],
        ground_truth=gt,
        provenance=prov,
        meta=meta,
    )


def _title_for(topic, dims, rng):
    cap = topic[:1].upper() + topic[1:]
    dt = dims["document_type"]
    if dt == "blog_post":
        return rng.choice(BLOG_TITLES).format(topic=topic, cap=cap)
    if dt == "think_tank_report":
        return rng.choice(REPORT_TITLES).format(topic=topic, cap=cap)
    return rng.choice(TITLE_TEMPLATES).format(topic=topic, cap=cap)


def _clean_title(title):
    title = (title or "").strip().replace("A Program of Research on ", "")
    return (title[:1].lower() + title[1:]) if title else "an unspecified problem"


def _generate_body(topic, dims, backend, model, rng):
    if backend == "anthropic":
        out = generate_with_anthropic(dims, topic, model)
        if out:
            return {"generated": out}, out, model
    sections = _sections_for(topic, dims, rng)
    text = "\n\n".join(f"{k.replace('_', ' ').title()}\n{v}" for k, v in sections.items())
    return sections, text, None


def _assemble(title, sections, cites, doc_type, human_text=None, override_body=None):
    parts = [title, ""]
    if human_text is not None:
        parts.append(human_text)
    elif override_body is not None:
        parts.append(override_body)
    else:
        for k, v in sections.items():
            parts.append(f"{k.replace('_', ' ').title()}\n{v}")
    parts.append("\n" + CITATION_HEADING.get(doc_type, "References"))
    parts.extend(f"{c.marker} https://doi.org/{c.doi}" for c in cites)
    return "\n".join(parts)


def _extract_budget(sections):
    for v in sections.values():  # prefer the stated total over a line item
        m = re.search(r"Total requested support is \$([\d,]+)", v)
        if m:
            return int(m.group(1).replace(",", ""))
    for v in sections.values():
        m = re.search(r"\$([\d,]+)", v)
        if m:
            return int(m.group(1).replace(",", ""))
    return None


# --------------------------------------------------------------------------- #
# Tuple enumeration (dimensions -> tuples, stratified for label balance)
# --------------------------------------------------------------------------- #
def build_tuples(n, tiers, doctypes, rng):
    per = max(1, n // len(AUTHORSHIP))
    tuples = []
    for auth in AUTHORSHIP:
        combos = []
        for dt in doctypes:
            defects = DEFECTS_BY_DOCTYPE[dt] if auth == "slop" else ["none"]
            for t, disc, a, x in itertools.product(tiers, DISCIPLINES, APPLICANT_TYPES, defects):
                combos.append(
                    dict(
                        authorship=auth,
                        document_type=dt,
                        institution_tier=t,
                        discipline=disc,
                        applicant_type=a,
                        defect=x,
                    )
                )
        rng.shuffle(combos)
        tuples.extend(combos[i % len(combos)] for i in range(per))
    rng.shuffle(tuples)
    return tuples


def coverage_report(records):
    dims = [
        "authorship",
        "document_type",
        "institution_tier",
        "discipline",
        "applicant_type",
        "defect",
    ]
    report = {d: dict(Counter(r.dimensions[d] for r in records)) for d in dims}
    tuple_keys = Counter(tuple(sorted(r.dimensions.items())) for r in records)
    report["_tuples"] = {"unique": len(tuple_keys), "total_records": len(records)}
    return report


def add_near_duplicates(records, k, rng):
    """Append k near-duplicate clones: each is a light paraphrase of an existing
    record, flagged is_near_duplicate with duplicate_of pointing at its original.
    Exercises the similarity/duplication check ("similar to existing submissions").
    """
    base_n = len(records)
    clones = []
    for i in range(k):
        orig = rng.choice(records)
        clones.append(
            Record(
                id=f"synth_{base_n + i:05d}",
                label=orig.label,
                dimensions=dict(orig.dimensions),
                title=orig.title,
                topic=orig.topic,
                sections=dict(orig.sections),
                text=_launder(orig.text, rng),  # light paraphrase -> near, not exact
                citations=[dict(c) for c in orig.citations],
                ground_truth={**orig.ground_truth, "is_near_duplicate": True},
                provenance=dict(orig.provenance),
                meta={**orig.meta, "duplicate_of": orig.id},
            )
        )
    return clones


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="Generate dimension-covered synthetic funding documents."
    )
    ap.add_argument(
        "--n", type=int, default=240, help="total records (split evenly across authorship labels)"
    )
    ap.add_argument(
        "--doctypes",
        nargs="+",
        default=DOCUMENT_TYPES,
        choices=DOCUMENT_TYPES,
        help="document types = the document_type dimension",
    )
    ap.add_argument(
        "--tiers",
        nargs="+",
        default=["R1", "R2"],
        help="Carnegie institution tiers = the institution_tier dimension",
    )
    ap.add_argument("--backend", choices=["template", "anthropic"], default="template")
    ap.add_argument("--model", default="claude-sonnet-5", help="model id for --backend anthropic")
    ap.add_argument("--offline", action="store_true", help="fabricate seeds (no NIH pulls)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="./synthetic_proposals")
    ap.add_argument(
        "--near-dups",
        type=int,
        default=0,
        help="append N near-duplicate clones (is_near_duplicate + duplicate_of)",
    )
    ap.add_argument(
        "--verify-dois", action="store_true", help="HEAD-check each DOI (slow, network)"
    )
    args = ap.parse_args()

    rng = random.Random(args.seed)
    tiers = args.tiers
    os.makedirs(args.out, exist_ok=True)

    per_label = max(1, args.n // len(AUTHORSHIP))
    n_human_each = max(5, per_label // len(tiers))
    seed_buckets = collect_seeds(tiers, n_human_each, args.offline, rng)

    tuples = build_tuples(args.n, tiers, args.doctypes, rng)
    records = []
    for idx, dims in enumerate(tuples):
        bucket = seed_buckets.get(dims["institution_tier"]) or next(iter(seed_buckets.values()))
        seed = rng.choice(bucket)
        records.append(build_record(idx, dims, seed, args.backend, args.model, rng))

    if args.near_dups:
        records += add_near_duplicates(records, args.near_dups, rng)

    if args.verify_dois:
        _verify_dois(records)

    _write_outputs(args, records, tiers)


def _write_outputs(args, records, tiers):
    corpus_path = os.path.join(args.out, "corpus.jsonl")
    with open(corpus_path, "w") as f:
        for r in records:
            f.write(json.dumps(asdict(r)) + "\n")

    manifest_path = os.path.join(args.out, "manifest.csv")
    with open(manifest_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "id",
                "label",
                "document_type",
                "institution_tier",
                "discipline",
                "applicant_type",
                "defect",
                "ai_generated",
                "laundered",
                "has_fabricated_citations",
                "has_mismatched_citations",
                "overclaims",
                "budget_inflated",
                "budget_math",
                "missing_methods",
                "is_near_duplicate",
                "n_citations",
                "n_unresolvable_citations",
                "n_mismatched_citations",
                "duplicate_of",
                "backend",
                "seed_source",
            ]
        )
        for r in records:
            d, g = r.dimensions, r.ground_truth
            w.writerow(
                [
                    r.id,
                    r.label,
                    d["document_type"],
                    d["institution_tier"],
                    d["discipline"],
                    d["applicant_type"],
                    d["defect"],
                    g["ai_generated"],
                    g["laundered"],
                    g["has_fabricated_citations"],
                    g["has_mismatched_citations"],
                    g["overclaims"],
                    g["budget_inflated"],
                    g["budget_math"],
                    g["missing_methods"],
                    g["is_near_duplicate"],
                    r.meta["n_citations"],
                    r.meta["n_unresolvable_citations"],
                    r.meta["n_mismatched_citations"],
                    r.meta["duplicate_of"] or "",
                    r.provenance["backend"],
                    r.provenance["seed_source"],
                ]
            )

    coverage_path = os.path.join(args.out, "coverage.json")
    with open(coverage_path, "w") as f:
        json.dump(coverage_report(records), f, indent=2)

    meta_path = os.path.join(args.out, "run_meta.json")
    with open(meta_path, "w") as f:
        json.dump(
            {
                "generated_utc": datetime.now(UTC).isoformat(),
                "n_records": len(records),
                "near_dups": args.near_dups,
                "doctypes": args.doctypes,
                "tiers": tiers,
                "backend": args.backend,
                "model": args.model if args.backend == "anthropic" else None,
                "seed": args.seed,
                "offline": args.offline,
            },
            f,
            indent=2,
        )

    print(f"Wrote {len(records)} records to {args.out}/")
    for p in (corpus_path, manifest_path, coverage_path, meta_path):
        print(f"  {os.path.basename(p)}: {p}")


def _verify_dois(records):
    seen = {}
    for r in records:
        for c in r.citations:
            if c["doi"] not in seen:
                seen[c["doi"]] = _doi_resolves(c["doi"])
            c["resolves"] = seen[c["doi"]]


def _doi_resolves(doi):
    req = urllib.request.Request(
        f"https://doi.org/{doi}", method="HEAD", headers={"User-Agent": "slopchecker-synth/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status < 400
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


if __name__ == "__main__":
    main()
