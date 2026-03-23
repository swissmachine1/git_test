#!/usr/bin/env python3
"""
HTML Analyzer & Lookalike Finder
=================================
Reads extracted website markdown files, uses Claude to perform a deep
multi-dimensional analysis of what businesses have in common, then builds
a "lookalike profile" — a precise fingerprint you can use to find similar
companies — and optionally scores a new list of candidates against it.

Three phases:
  1. Per-site extraction   — structured business intelligence from each site
  2. Deep analysis         — what the businesses share (with adaptive thinking)
  3. Lookalike profile     — a scored fingerprint + discovery playbook

Usage:
    # Full pipeline on a directory of .md files
    python html_analyzer.py --input-dir html_output

    # Score NEW candidates against an existing profile
    python html_analyzer.py --profile lookalike_profile.json --candidates new_sites/

    # Explicit files + custom output
    python html_analyzer.py a.md b.md c.md --output report.md

Requirements:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=your_key_here
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    sys.exit("Missing dependency: pip install anthropic")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM = (
    "You are a business intelligence analyst. "
    "Extract every available signal from website content. "
    "Return only a valid JSON object — no markdown, no explanation."
)

EXTRACTION_PROMPT = """\
Analyze this website content and extract all business signals.
Return a single JSON object matching the schema below exactly.

<content>
{content}
</content>

{{
  "business_name": "string",
  "industry": "string",
  "sub_industry": "string — be specific",
  "business_model": "SaaS | e-commerce | marketplace | agency | media | consultancy | other",
  "go_to_market": "self-serve | sales-led | product-led | channel | hybrid",
  "products_services": ["exhaustive list"],
  "target_audience": {{
    "primary": "string",
    "secondary": "string or null",
    "company_size": "individual | SMB | mid-market | enterprise | all",
    "technical_level": "non-technical | mixed | technical",
    "job_titles_targeted": ["titles/roles mentioned or implied"]
  }},
  "pricing": {{
    "model": "free | freemium | subscription | usage-based | one-time | contact-for-pricing | mixed",
    "tiers": ["tier names"],
    "price_points": ["specific prices or ranges"],
    "free_trial": true,
    "money_back_guarantee": false
  }},
  "value_propositions": ["top 5, verbatim or near-verbatim"],
  "primary_pain_point": "the single core problem they solve",
  "outcome_promised": "the end state they promise customers",
  "cta_patterns": ["every call-to-action, exact wording"],
  "trust_signals": {{
    "has_testimonials": true,
    "has_case_studies": true,
    "has_customer_logos": true,
    "has_reviews": false,
    "certifications": ["list"],
    "awards": ["list"],
    "review_rating": "string or null",
    "customer_count": "string or null",
    "years_in_business": "string or null",
    "social_proof_phrases": ["exact phrases"]
  }},
  "content_structure": {{
    "page_sections": ["sections in order"],
    "navigation": ["primary nav items"],
    "footer_categories": ["footer link groups"],
    "has_blog": true,
    "has_docs": false,
    "has_resource_hub": false,
    "has_pricing_page": true,
    "has_about_page": true,
    "has_careers_page": false
  }},
  "brand": {{
    "voice": "professional | casual | technical | friendly | authoritative | bold | empathetic",
    "tone_adjectives": ["3-5 words describing tone"],
    "key_phrases": ["memorable taglines or repeated phrases"],
    "color_signals": ["any color/design signals in content"]
  }},
  "seo": {{
    "primary_keywords": ["top 5 keywords by frequency"],
    "long_tail_topics": ["topic clusters"],
    "meta_description": "if found"
  }},
  "geography": "global | US | North America | Europe | APAC | local | string",
  "languages": ["languages present"],
  "contact_methods": ["email | phone | chat | form | calendly | etc."],
  "integrations": ["third-party tools/platforms mentioned"],
  "tech_stack_signals": ["CMS, hosting, analytics, frameworks detected"],
  "social_platforms": ["platforms linked"],
  "differentiators": ["claimed unique advantages"],
  "competitors_mentioned": ["any competitors named"],
  "partnerships_mentioned": ["partners, investors, or affiliates named"],
  "funding_signals": ["any funding/investment mentions"],
  "team_size_signals": ["headcount hints or 'small team' type language"]
}}
"""

ANALYSIS_SYSTEM = (
    "You are a world-class business analyst, market researcher, and "
    "competitive intelligence expert. Produce exhaustive, highly specific "
    "analysis — cite actual data points, avoid vague generalizations. "
    "Think like a top-tier VC, McKinsey partner, and growth strategist combined."
)

ANALYSIS_PROMPT = """\
I extracted structured business intelligence from {n} websites.
Perform the deepest possible comparative analysis to identify everything these
businesses have in common. Be specific — reference actual data from the records.

{data}

---

Write the full report following this structure:

# Business Commonality Deep Analysis Report
*{n} businesses analyzed*

## 1. Business Model & Market Position
- Shared core model patterns
- Market segment and positioning
- Competitive moat and defensibility signals
- Stage of market maturity implied

## 2. Target Audience & Buyer Profile
- Shared demographics and firmographics
- Job titles and decision-maker profiles
- Common pain points they address
- Self-serve vs. sales-led signals

## 3. Pricing Architecture & Monetization
- Shared pricing model patterns
- Value metric alignment
- Price anchoring and tier strategies
- Friction in the purchase journey

## 4. Value Proposition DNA
- Core value prop themes
- Feature-vs-benefit framing
- Outcome language patterns
- ROI framing approaches

## 5. Content & SEO Strategy
- Shared keyword clusters and topics
- Content marketing maturity
- Thought leadership positioning
- Documentation and resource strategies

## 6. Trust & Credibility Architecture
- Social proof types and hierarchy
- Specificity of claims (vague vs. quantified)
- Authority-building techniques
- Implicit credibility frameworks

## 7. Conversion & CTA Strategy
- CTA verb and framing patterns
- Funnel entry points (trial, demo, contact, sign-up)
- Friction reduction and commitment ladder
- Low-risk offers used

## 8. Technology & Integration Ecosystem
- Tech stack and platform signals
- Integration strategy patterns
- Technical sophistication of offerings
- Platform dependency signals

## 9. Brand Voice & Communication Style
- Tone and personality patterns
- Vocabulary and language complexity
- Messaging framework similarities
- Storytelling and narrative approach

## 10. Information Architecture & UX Patterns
- Page structure and section ordering
- Navigation priority patterns
- Footer strategy
- Content length and density signals

## 11. Distribution & Growth Signals
- Implied acquisition channels
- Partnership and ecosystem plays
- Geographic ambition
- PLG or viral loop signals

## 12. Gaps & Blind Spots
- Topics, pages, or tactics conspicuously absent
- Risks they don't mention
- Audiences they ignore
- What they explicitly DON'T compete on

## 13. Deep Strategic Synthesis
- What these patterns reveal about this market
- The implicit rules of competing in this space
- Where real differentiation opportunities lie
- What a new entrant must replicate

## 14. The Common Playbook (Executive Summary)
Tight, actionable synthesis: the exact playbook these companies share —
what every business in this space must do to be taken seriously.
"""

PROFILE_SYSTEM = (
    "You are a sales intelligence and lookalike modeling expert. "
    "Your job is to build precise Ideal Customer Profiles (ICPs) and "
    "lookalike company fingerprints that sales and marketing teams use "
    "to find more companies just like their best customers. "
    "Be extremely specific — vague profiles find nothing."
)

PROFILE_PROMPT = """\
Based on this deep analysis of {n} businesses, build a comprehensive
LOOKALIKE COMPANY PROFILE — a precise fingerprint that can be used to
identify similar companies in the wild.

Analysis:
{analysis}

Raw extracted data:
{data}

---

Produce the following as a JSON object:

{{
  "profile_name": "short descriptive name for this archetype",
  "profile_summary": "2-3 sentence description of the ideal lookalike company",

  "must_have_signals": [
    "non-negotiable criteria — a company MUST match ALL of these",
    "e.g. 'B2B SaaS with self-serve signup'",
    "e.g. 'Targets SMB or mid-market, not enterprise-only'",
    "be specific, not vague"
  ],

  "strong_signals": [
    "present in most but not all — high confidence indicators",
    "e.g. 'Has a free tier or trial'",
    "e.g. 'Uses feature-comparison pricing table'"
  ],

  "weak_signals": [
    "nice-to-have or supporting indicators",
    "e.g. 'Has a public API or integrations page'"
  ],

  "disqualifying_signals": [
    "signals that EXCLUDE a company from being a lookalike",
    "e.g. 'Enterprise-only with no self-serve'",
    "e.g. 'Purely services/consulting with no product'"
  ],

  "industry_tags": ["list of industries where lookalikes are found"],
  "business_model_tags": ["e.g. SaaS, marketplace"],
  "company_size_range": {{
    "employees_min": 10,
    "employees_max": 500,
    "revenue_min": "$1M ARR",
    "revenue_max": "$50M ARR"
  }},

  "search_keywords": [
    "keywords to use in Google/LinkedIn to find lookalikes",
    "e.g. 'self-serve B2B SaaS [industry]'",
    "e.g. '[pain point] software for [audience]'"
  ],

  "linkedin_search_filters": {{
    "industries": ["LinkedIn industry categories"],
    "job_titles_to_find_at_target": ["titles of people to target"],
    "company_keywords": ["keywords for company descriptions"],
    "headcount_range": "11-200"
  }},

  "discovery_channels": [
    "where to find these companies",
    "e.g. 'G2 category: [category name]'",
    "e.g. 'ProductHunt launches tagged [tag]'",
    "e.g. 'YC companies in [batch range] doing [description]'",
    "e.g. 'Capterra category: [name]'",
    "e.g. 'Crunchbase filter: [industry] + seed/series-A + [keywords]'"
  ],

  "scoring_rubric": [
    {{
      "criterion": "has self-serve signup or free trial",
      "weight": 10,
      "how_to_check": "look for 'Start free', 'Sign up', 'Try free' CTAs on homepage"
    }},
    {{
      "criterion": "targets SMB or mid-market",
      "weight": 8,
      "how_to_check": "check pricing page; look for per-seat pricing under $200/mo"
    }}
  ],

  "example_discovery_queries": [
    "example Google search queries",
    "example LinkedIn Sales Navigator filters",
    "example Crunchbase filters",
    "example G2 or Capterra category searches"
  ],

  "red_flags": [
    "warning signs that a candidate is NOT actually a lookalike despite surface similarity"
  ]
}}
"""

SCORING_SYSTEM = (
    "You are a sales intelligence expert scoring candidate companies against "
    "a lookalike profile. Be objective, specific, and use evidence from the "
    "company's content to justify each score."
)

SCORING_PROMPT = """\
Score this candidate company against the lookalike profile.
Return a JSON object only — no explanation outside the JSON.

Lookalike Profile:
{profile}

Candidate company content:
<content>
{content}
</content>

Return:
{{
  "company_name": "string",
  "overall_score": 0-100,
  "verdict": "strong match | moderate match | weak match | not a match",
  "must_have_met": [
    {{"criterion": "string", "met": true, "evidence": "quote or observation"}}
  ],
  "strong_signals_met": [
    {{"signal": "string", "met": true, "evidence": "string"}}
  ],
  "disqualifiers_triggered": ["list any disqualifying signals found"],
  "scoring_breakdown": [
    {{"criterion": "string", "weight": 10, "score": 0-10, "reasoning": "string"}}
  ],
  "summary": "2-3 sentence summary of why this is or isn't a match",
  "top_similarities": ["3-5 most compelling similarities"],
  "key_differences": ["3-5 most notable differences"]
}}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MAX_CONTENT_CHARS = 40_000


def load_files(paths: list[str]) -> list[dict]:
    sites = []
    for path in paths:
        p = Path(path)
        if not p.exists():
            print(f"  Warning: {path} not found, skipping.")
            continue
        content = p.read_text(encoding="utf-8")
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + "\n\n[truncated]"
        sites.append({"filename": p.name, "content": content})
    return sites


def stream_json(client: anthropic.Anthropic, system: str, user: str, max_tokens: int = 4096) -> dict:
    """Call Claude and parse the JSON response."""
    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_object"}},
    ) as stream:
        final = stream.get_final_message()

    text = next((b.text for b in final.content if b.type == "text"), "{}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_parse_error": text[:500]}


def stream_text(client: anthropic.Anthropic, system: str, user: str,
                max_tokens: int = 16000, thinking: bool = True) -> str:
    """Call Claude with adaptive thinking + streaming, print live, return full text."""
    kwargs = {}
    if thinking:
        kwargs["thinking"] = {"type": "adaptive"}

    parts: list[str] = []
    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        **kwargs,
    ) as stream:
        for event in stream:
            if event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    print(event.delta.text, end="", flush=True)
                    parts.append(event.delta.text)

    print()
    return "".join(parts)


def build_data_block(all_data: list[dict]) -> str:
    lines = []
    for i, d in enumerate(all_data, 1):
        source = d.get("_source", f"site_{i}")
        clean = {k: v for k, v in d.items() if k != "_source"}
        lines.append(
            f"### Site {i} — {source}\n```json\n{json.dumps(clean, indent=2)}\n```"
        )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Pipeline phases
# ---------------------------------------------------------------------------

def phase1_extract(client: anthropic.Anthropic, sites: list[dict]) -> list[dict]:
    print(f"\nPhase 1: Extracting business intelligence ({len(sites)} sites)...")
    all_data = []
    for site in sites:
        print(f"  [{site['filename']}] ... ", end="", flush=True)
        data = stream_json(
            client,
            EXTRACTION_SYSTEM,
            EXTRACTION_PROMPT.format(content=site["content"]),
            max_tokens=4096,
        )
        data["_source"] = site["filename"]
        all_data.append(data)
        print("done")
    return all_data


def phase2_analyze(client: anthropic.Anthropic, all_data: list[dict]) -> str:
    print(f"\nPhase 2: Deep comparative analysis (adaptive thinking + streaming)...")
    print("-" * 72)
    data_block = build_data_block(all_data)
    analysis = stream_text(
        client,
        ANALYSIS_SYSTEM,
        ANALYSIS_PROMPT.format(n=len(all_data), data=data_block),
        max_tokens=16000,
        thinking=True,
    )
    print("-" * 72)
    return analysis


def phase3_profile(client: anthropic.Anthropic, all_data: list[dict], analysis: str) -> dict:
    print("\nPhase 3: Building lookalike company profile...")
    data_block = build_data_block(all_data)
    profile = stream_json(
        client,
        PROFILE_SYSTEM,
        PROFILE_PROMPT.format(n=len(all_data), analysis=analysis, data=data_block),
        max_tokens=8192,
    )
    return profile


def phase4_score(client: anthropic.Anthropic, candidates: list[dict], profile: dict) -> list[dict]:
    print(f"\nPhase 4: Scoring {len(candidates)} candidate(s) against profile...")
    profile_str = json.dumps(profile, indent=2)
    scores = []
    for site in candidates:
        print(f"  [{site['filename']}] ... ", end="", flush=True)
        result = stream_json(
            client,
            SCORING_SYSTEM,
            SCORING_PROMPT.format(profile=profile_str, content=site["content"]),
            max_tokens=4096,
        )
        result["_source"] = site["filename"]
        scores.append(result)
        verdict = result.get("verdict", "unknown")
        score = result.get("overall_score", "?")
        print(f"score {score}/100 — {verdict}")

    # Sort by score descending
    scores.sort(key=lambda x: x.get("overall_score", 0), reverse=True)
    return scores


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Deep business analysis and lookalike company finder. "
            "Extracts business intelligence from websites and finds similar companies."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline: analyze sites and build a lookalike profile
  python html_analyzer.py --input-dir html_output

  # Score new candidate companies against an existing profile
  python html_analyzer.py --profile lookalike_profile.json --candidates new_sites/

  # Explicit files
  python html_analyzer.py stripe.md braintree.md adyen.md
        """,
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help="Markdown files to analyze (output from html_extractor.py).",
    )
    parser.add_argument(
        "--input-dir", "-i",
        metavar="DIR",
        help="Directory of .md files from html_extractor.py.",
    )
    parser.add_argument(
        "--candidates", "-c",
        metavar="DIR",
        help="Directory of candidate .md files to score against the profile.",
    )
    parser.add_argument(
        "--profile", "-p",
        metavar="FILE",
        help="Existing lookalike_profile.json — skip phases 1-3 and go straight to scoring.",
    )
    parser.add_argument(
        "--output", "-o",
        default="analysis_report.md",
        metavar="FILE",
        help="Output path for the analysis report (default: analysis_report.md).",
    )
    parser.add_argument(
        "--profile-output",
        default="lookalike_profile.json",
        metavar="FILE",
        help="Output path for the lookalike profile JSON (default: lookalike_profile.json).",
    )
    parser.add_argument(
        "--scores-output",
        default="candidate_scores.json",
        metavar="FILE",
        help="Output path for candidate scores (default: candidate_scores.json).",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY environment variable is not set.")
    client = anthropic.Anthropic(api_key=api_key)

    # ---- Mode: score-only (skip analysis, use existing profile) ----
    if args.profile:
        profile_path = Path(args.profile)
        if not profile_path.exists():
            sys.exit(f"Error: profile file '{args.profile}' not found.")
        profile = json.loads(profile_path.read_text())

        if not args.candidates:
            sys.exit("Error: --candidates dir required when using --profile.")

        cand_dir = Path(args.candidates)
        if not cand_dir.is_dir():
            sys.exit(f"Error: '{args.candidates}' is not a directory.")

        cand_paths = sorted(str(p) for p in cand_dir.glob("*.md"))
        if not cand_paths:
            sys.exit(f"No .md files found in {args.candidates}")

        candidates = load_files(cand_paths)
        scores = phase4_score(client, candidates, profile)

        out = Path(args.scores_output)
        out.write_text(json.dumps(scores, indent=2), encoding="utf-8")
        print(f"\nScores saved → {out}")

        # Print summary table
        print("\n--- Candidate Ranking ---")
        for s in scores:
            print(
                f"  {s.get('overall_score', '?'):>3}/100  "
                f"{s.get('verdict', ''):20}  "
                f"{s.get('_source', '')}"
            )
        return

    # ---- Mode: full pipeline ----
    file_paths = list(args.files)
    if args.input_dir:
        d = Path(args.input_dir)
        if not d.is_dir():
            sys.exit(f"Error: '{args.input_dir}' is not a directory.")
        file_paths += sorted(str(p) for p in d.glob("*.md"))

    if not file_paths:
        parser.print_help()
        sys.exit(1)

    if len(file_paths) < 2:
        print("Note: comparative analysis works best with 2+ websites.")

    print(f"Loading {len(file_paths)} file(s)...")
    sites = load_files(file_paths)
    if not sites:
        sys.exit("No files could be loaded.")

    # Phase 1: extract
    all_data = phase1_extract(client, sites)

    # Phase 2: deep analysis
    analysis = phase2_analyze(client, all_data)
    Path(args.output).write_text(analysis, encoding="utf-8")
    print(f"\nAnalysis report saved → {args.output}")

    # Phase 3: build lookalike profile
    profile = phase3_profile(client, all_data, analysis)
    Path(args.profile_output).write_text(json.dumps(profile, indent=2), encoding="utf-8")
    print(f"Lookalike profile saved → {args.profile_output}")

    # Phase 4 (optional): score candidate sites
    if args.candidates:
        cand_dir = Path(args.candidates)
        if not cand_dir.is_dir():
            print(f"Warning: '{args.candidates}' is not a directory — skipping scoring.")
        else:
            cand_paths = sorted(str(p) for p in cand_dir.glob("*.md"))
            candidates = load_files(cand_paths)
            if candidates:
                scores = phase4_score(client, candidates, profile)
                Path(args.scores_output).write_text(
                    json.dumps(scores, indent=2), encoding="utf-8"
                )
                print(f"Candidate scores saved → {args.scores_output}")

                print("\n--- Candidate Ranking ---")
                for s in scores:
                    print(
                        f"  {s.get('overall_score', '?'):>3}/100  "
                        f"{s.get('verdict', ''):20}  "
                        f"{s.get('_source', '')}"
                    )

    # Print profile summary
    print("\n--- Lookalike Profile Summary ---")
    print(f"  Name    : {profile.get('profile_name', 'N/A')}")
    print(f"  Summary : {profile.get('profile_summary', 'N/A')}")
    must = profile.get("must_have_signals", [])
    if must:
        print("  Must-have signals:")
        for m in must[:5]:
            print(f"    • {m}")


if __name__ == "__main__":
    main()
