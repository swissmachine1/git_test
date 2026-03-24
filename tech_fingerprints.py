#!/usr/bin/env python3
"""
Tech Fingerprints — technology detection engine.

Two modes:
  1. Built-in signatures (~90 technologies) — instant, no API cost.
     Regex patterns matched against raw HTML text.
  2. Claude-generated custom fingerprints — given competitor HTML,
     Claude extracts proprietary/unknown technology signals and returns
     additional regex patterns to scan for across the TAM.

Usage:
    from tech_fingerprints import scan_html, scan_html_file, SIGNATURES
    from tech_fingerprints import generate_custom_fingerprints  # needs ANTHROPIC_API_KEY
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Built-in signature database
# Each entry: list of regex patterns searched against the full raw HTML text.
# A single match in any pattern → technology detected.
# ---------------------------------------------------------------------------

SIGNATURES: dict[str, dict] = {

    # ── Frontend Frameworks ─────────────────────────────────────────────────
    "react": {
        "name": "React",
        "category": "Frontend Framework",
        "homepage": "react.dev",
        "patterns": [
            r"react(?:\.min)?\.js",
            r"react-dom",
            r"/react@\d",
            r"data-reactroot",
            r"data-reactid",
            r"__REACT_DEVTOOLS",
            r"_reactRootContainer",
        ],
    },
    "nextjs": {
        "name": "Next.js",
        "category": "Frontend Framework",
        "homepage": "nextjs.org",
        "patterns": [
            r"/_next/static/",
            r"__NEXT_DATA__",
            r"next/dist/",
            r"\"framework\":\s*\"next\"",
        ],
    },
    "vue": {
        "name": "Vue.js",
        "category": "Frontend Framework",
        "homepage": "vuejs.org",
        "patterns": [
            r"vue(?:\.min)?\.js",
            r"/vue@\d",
            r"v-bind:|v-on:|v-if=|v-for=|v-model=",
            r"__vue_app__",
            r"data-v-[a-f0-9]{7,}",
        ],
    },
    "nuxt": {
        "name": "Nuxt.js",
        "category": "Frontend Framework",
        "homepage": "nuxt.com",
        "patterns": [
            r"/_nuxt/",
            r"__NUXT__",
            r"nuxt(?:\.min)?\.js",
        ],
    },
    "angular": {
        "name": "Angular",
        "category": "Frontend Framework",
        "homepage": "angular.io",
        "patterns": [
            r"ng-version=",
            r"angular(?:\.min)?\.js",
            r"/angular@\d",
            r"ng-app=",
            r"\[ngModel\]",
            r"platformBrowserDynamic",
        ],
    },
    "svelte": {
        "name": "Svelte",
        "category": "Frontend Framework",
        "homepage": "svelte.dev",
        "patterns": [
            r"svelte-[a-z0-9]{7}",
            r"/__svelte",
            r"svelte/internal",
        ],
    },
    "remix": {
        "name": "Remix",
        "category": "Frontend Framework",
        "homepage": "remix.run",
        "patterns": [
            r"/__remix_manifest",
            r"window\.__remixContext",
            r"\"framework\":\s*\"remix\"",
        ],
    },
    "gatsby": {
        "name": "Gatsby",
        "category": "Frontend Framework",
        "homepage": "gatsbyjs.com",
        "patterns": [
            r"window\.___gatsby",
            r"/static/gatsby",
            r"gatsby-image",
        ],
    },

    # ── CSS Frameworks ──────────────────────────────────────────────────────
    "tailwind": {
        "name": "Tailwind CSS",
        "category": "CSS Framework",
        "homepage": "tailwindcss.com",
        "patterns": [
            r"tailwindcss",
            r"cdn\.tailwindcss\.com",
            r"class=\"[^\"]*(?:flex|grid|text-\w+-\d{3}|bg-\w+-\d{3}|px-\d|py-\d|mx-auto|rounded-\w+|font-\w+)[^\"]*\"",
        ],
    },
    "bootstrap": {
        "name": "Bootstrap",
        "category": "CSS Framework",
        "homepage": "getbootstrap.com",
        "patterns": [
            r"bootstrap(?:\.min)?\.css",
            r"bootstrap(?:\.min)?\.js",
            r"cdn\.jsdelivr\.net/npm/bootstrap",
            r"class=\"[^\"]*(?:navbar|btn-primary|container-fluid|col-md-\d|row)[^\"]*\"",
        ],
    },
    "material_ui": {
        "name": "Material UI (MUI)",
        "category": "CSS Framework",
        "homepage": "mui.com",
        "patterns": [
            r"MuiButton|MuiBox|MuiTypography|MuiContainer",
            r"@mui/material",
            r"makeStyles|withStyles",
        ],
    },
    "chakra_ui": {
        "name": "Chakra UI",
        "category": "CSS Framework",
        "homepage": "chakra-ui.com",
        "patterns": [
            r"chakra-",
            r"@chakra-ui",
        ],
    },
    "ant_design": {
        "name": "Ant Design",
        "category": "CSS Framework",
        "homepage": "ant.design",
        "patterns": [
            r"antd(?:\.min)?\.css",
            r"ant-btn|ant-form|ant-table|ant-modal",
            r"@ant-design",
        ],
    },

    # ── Analytics ───────────────────────────────────────────────────────────
    "google_analytics": {
        "name": "Google Analytics (UA)",
        "category": "Analytics",
        "homepage": "analytics.google.com",
        "patterns": [
            r"google-analytics\.com/analytics\.js",
            r"google-analytics\.com/ga\.js",
            r"GoogleAnalyticsObject",
            r"UA-\d{5,}-\d+",
        ],
    },
    "google_analytics_4": {
        "name": "Google Analytics 4",
        "category": "Analytics",
        "homepage": "analytics.google.com",
        "patterns": [
            r"googletagmanager\.com/gtag/js\?id=G-",
            r"gtag\(['\"]config['\"],\s*['\"]G-",
            r"G-[A-Z0-9]{8,10}",
        ],
    },
    "google_tag_manager": {
        "name": "Google Tag Manager",
        "category": "Tag Manager",
        "homepage": "tagmanager.google.com",
        "patterns": [
            r"googletagmanager\.com/gtm\.js",
            r"GTM-[A-Z0-9]{5,}",
            r"google_tag_manager",
        ],
    },
    "segment": {
        "name": "Segment",
        "category": "Customer Data Platform",
        "homepage": "segment.com",
        "patterns": [
            r"cdn\.segment(?:\.io|\.com)/analytics\.js",
            r"analytics\.identify\(",
            r"analytics\.track\(",
            r"window\.analytics",
            r"segmentio",
        ],
    },
    "mixpanel": {
        "name": "Mixpanel",
        "category": "Analytics",
        "homepage": "mixpanel.com",
        "patterns": [
            r"cdn\.mxpnl\.com",
            r"mixpanel\.com/libs",
            r"mixpanel\.init\(",
            r"window\.mixpanel",
        ],
    },
    "amplitude": {
        "name": "Amplitude",
        "category": "Analytics",
        "homepage": "amplitude.com",
        "patterns": [
            r"cdn\.amplitude\.com",
            r"amplitude\.getInstance\(",
            r"window\.amplitude",
            r"amplitude-js",
        ],
    },
    "heap": {
        "name": "Heap",
        "category": "Analytics",
        "homepage": "heap.io",
        "patterns": [
            r"cdn\.heapanalytics\.com",
            r"heap\.load\(",
            r"window\.heap",
            r"heapanalytics",
        ],
    },
    "hotjar": {
        "name": "Hotjar",
        "category": "Analytics",
        "homepage": "hotjar.com",
        "patterns": [
            r"static\.hotjar\.com",
            r"hjid:",
            r"hjsv:",
            r"window\.hj\b",
            r"hotjar\.com",
        ],
    },
    "fullstory": {
        "name": "FullStory",
        "category": "Analytics",
        "homepage": "fullstory.com",
        "patterns": [
            r"fullstory\.com/s/fs\.js",
            r"window\[\"_fs_",
            r"FS\.identify\(",
            r"fullstory",
        ],
    },
    "posthog": {
        "name": "PostHog",
        "category": "Analytics",
        "homepage": "posthog.com",
        "patterns": [
            r"app\.posthog\.com",
            r"posthog\.init\(",
            r"window\.posthog",
            r"posthog-js",
        ],
    },
    "plausible": {
        "name": "Plausible Analytics",
        "category": "Analytics",
        "homepage": "plausible.io",
        "patterns": [
            r"plausible\.io/js/",
            r"data-domain.*plausible",
        ],
    },
    "matomo": {
        "name": "Matomo",
        "category": "Analytics",
        "homepage": "matomo.org",
        "patterns": [
            r"matomo\.js",
            r"piwik\.js",
            r"_paq\.push",
            r"matomo\.php",
        ],
    },
    "logrocket": {
        "name": "LogRocket",
        "category": "Session Recording",
        "homepage": "logrocket.com",
        "patterns": [
            r"cdn\.logrocket\.io",
            r"LogRocket\.init\(",
            r"window\.LogRocket",
        ],
    },

    # ── Advertising Pixels ──────────────────────────────────────────────────
    "facebook_pixel": {
        "name": "Meta (Facebook) Pixel",
        "category": "Advertising",
        "homepage": "facebook.com/business",
        "patterns": [
            r"connect\.facebook\.net/.*fbevents\.js",
            r"fbq\('init'",
            r"_fbq\s*=",
            r"facebook-pixel",
        ],
    },
    "google_ads": {
        "name": "Google Ads",
        "category": "Advertising",
        "homepage": "ads.google.com",
        "patterns": [
            r"googleadservices\.com",
            r"AW-\d{9,}",
            r"gtag\(['\"]config['\"],\s*['\"]AW-",
            r"google_conversion",
        ],
    },
    "linkedin_insight": {
        "name": "LinkedIn Insight Tag",
        "category": "Advertising",
        "homepage": "linkedin.com/help/lms",
        "patterns": [
            r"snap\.licdn\.com",
            r"linkedin\.com/li\.lms-analytics",
            r"_linkedin_partner_id",
            r"linkedin_data_partner_id",
        ],
    },
    "twitter_pixel": {
        "name": "X (Twitter) Pixel",
        "category": "Advertising",
        "homepage": "ads.twitter.com",
        "patterns": [
            r"static\.ads-twitter\.com",
            r"twq\('init'",
            r"twq\('event'",
            r"twitter_conversion",
        ],
    },
    "tiktok_pixel": {
        "name": "TikTok Pixel",
        "category": "Advertising",
        "homepage": "ads.tiktok.com",
        "patterns": [
            r"analytics\.tiktok\.com",
            r"ttq\.load\(",
            r"window\.TiktokAnalyticsObject",
        ],
    },

    # ── Chat & Support ──────────────────────────────────────────────────────
    "intercom": {
        "name": "Intercom",
        "category": "Customer Support",
        "homepage": "intercom.com",
        "patterns": [
            r"widget\.intercom\.io",
            r"js\.intercomcdn\.com",
            r"window\.Intercom\b",
            r"intercomSettings",
            r"app_id.*intercom",
        ],
    },
    "drift": {
        "name": "Drift",
        "category": "Customer Support",
        "homepage": "drift.com",
        "patterns": [
            r"js\.driftt\.com",
            r"drift\.com/include\.js",
            r"window\.drift\b",
            r"driftt",
        ],
    },
    "zendesk": {
        "name": "Zendesk",
        "category": "Customer Support",
        "homepage": "zendesk.com",
        "patterns": [
            r"static\.zdassets\.com",
            r"zendesk\.com/embeddable",
            r"zE\(",
            r"zESettings",
            r"zendesk_widget",
        ],
    },
    "hubspot_chat": {
        "name": "HubSpot Chat",
        "category": "Customer Support",
        "homepage": "hubspot.com",
        "patterns": [
            r"js\.hs-scripts\.com",
            r"js\.hubspot\.com",
            r"hsq\.push",
            r"HubSpotConversations",
        ],
    },
    "crisp": {
        "name": "Crisp",
        "category": "Customer Support",
        "homepage": "crisp.chat",
        "patterns": [
            r"client\.crisp\.chat",
            r"window\.\$crisp\b",
            r"CRISP_WEBSITE_ID",
        ],
    },
    "freshdesk": {
        "name": "Freshdesk / Freshchat",
        "category": "Customer Support",
        "homepage": "freshdesk.com",
        "patterns": [
            r"freshbots\.io",
            r"freshchat\.com",
            r"freshdesk\.com/widget",
            r"fcWidget\.",
        ],
    },
    "helpscout": {
        "name": "Help Scout",
        "category": "Customer Support",
        "homepage": "helpscout.com",
        "patterns": [
            r"beacon-v2\.helpscout\.net",
            r"window\.Beacon\(",
            r"helpscout",
        ],
    },

    # ── CRM & Marketing Automation ──────────────────────────────────────────
    "hubspot": {
        "name": "HubSpot",
        "category": "CRM",
        "homepage": "hubspot.com",
        "patterns": [
            r"forms\.hubspot\.com",
            r"hbspt\.forms\.create",
            r"hubspot\.com/hs",
            r"hs-form",
        ],
    },
    "salesforce": {
        "name": "Salesforce",
        "category": "CRM",
        "homepage": "salesforce.com",
        "patterns": [
            r"salesforce\.com/widgets",
            r"force\.com",
            r"salesforceliveagent",
            r"pardot\.com",
        ],
    },
    "marketo": {
        "name": "Marketo",
        "category": "Marketing Automation",
        "homepage": "marketo.com",
        "patterns": [
            r"munchkin\.marketo\.net",
            r"Munchkin\.init\(",
            r"marketo\.com",
        ],
    },
    "klaviyo": {
        "name": "Klaviyo",
        "category": "Email Marketing",
        "homepage": "klaviyo.com",
        "patterns": [
            r"static\.klaviyo\.com",
            r"klaviyo\.js",
            r"window\._learnq\b",
        ],
    },
    "mailchimp": {
        "name": "Mailchimp",
        "category": "Email Marketing",
        "homepage": "mailchimp.com",
        "patterns": [
            r"chimpstatic\.com",
            r"list-manage\.com",
            r"mailchimp\.com/subscribe",
            r"mc-embedded-subscribe",
        ],
    },
    "customer_io": {
        "name": "Customer.io",
        "category": "Marketing Automation",
        "homepage": "customer.io",
        "patterns": [
            r"assets\.customer\.io",
            r"_cio\.identify\(",
            r"window\._cio\b",
        ],
    },

    # ── Payments ────────────────────────────────────────────────────────────
    "stripe": {
        "name": "Stripe",
        "category": "Payments",
        "homepage": "stripe.com",
        "patterns": [
            r"js\.stripe\.com",
            r"Stripe\s*\(",
            r"data-stripe=",
            r"stripe-button",
            r"pk_(?:live|test)_[A-Za-z0-9]{20,}",
        ],
    },
    "braintree": {
        "name": "Braintree",
        "category": "Payments",
        "homepage": "braintreepayments.com",
        "patterns": [
            r"js\.braintreegateway\.com",
            r"braintree\.setup\(",
            r"braintree-web",
        ],
    },
    "paypal": {
        "name": "PayPal",
        "category": "Payments",
        "homepage": "paypal.com",
        "patterns": [
            r"paypal\.com/sdk/js",
            r"paypalobjects\.com",
            r"paypal\.Buttons\(",
            r"data-paypal-button",
        ],
    },
    "paddle": {
        "name": "Paddle",
        "category": "Payments",
        "homepage": "paddle.com",
        "patterns": [
            r"cdn\.paddle\.com",
            r"Paddle\.Setup\(",
            r"Paddle\.Checkout",
        ],
    },
    "recurly": {
        "name": "Recurly",
        "category": "Payments",
        "homepage": "recurly.com",
        "patterns": [
            r"js\.recurly\.com",
            r"recurly\.configure\(",
            r"window\.recurly\b",
        ],
    },
    "chargebee": {
        "name": "Chargebee",
        "category": "Payments",
        "homepage": "chargebee.com",
        "patterns": [
            r"js\.chargebee\.com",
            r"Chargebee\.init\(",
            r"window\.Chargebee\b",
        ],
    },
    "square": {
        "name": "Square",
        "category": "Payments",
        "homepage": "squareup.com",
        "patterns": [
            r"web\.squarecdn\.com",
            r"squareupsandbox\.com",
            r"Square\.payments\(",
        ],
    },

    # ── Auth ─────────────────────────────────────────────────────────────────
    "auth0": {
        "name": "Auth0",
        "category": "Authentication",
        "homepage": "auth0.com",
        "patterns": [
            r"cdn\.auth0\.com",
            r"auth0\.js",
            r"auth0\.com/authorize",
            r"new Auth0\(",
        ],
    },
    "okta": {
        "name": "Okta",
        "category": "Authentication",
        "homepage": "okta.com",
        "patterns": [
            r"okta\.com/oauth2",
            r"okta-sign-in",
            r"OktaSignIn\(",
            r"cdn\.okta\.com",
        ],
    },
    "clerk": {
        "name": "Clerk",
        "category": "Authentication",
        "homepage": "clerk.com",
        "patterns": [
            r"clerk\.com/npm",
            r"clerk\.browser\.js",
            r"__clerk_",
            r"ClerkProvider",
        ],
    },
    "firebase_auth": {
        "name": "Firebase / Auth",
        "category": "Authentication",
        "homepage": "firebase.google.com",
        "patterns": [
            r"firebase\.googleapis\.com",
            r"gstatic\.com/firebasejs",
            r"firebase\.initializeApp",
            r"__FIREBASE_DEFAULTS__",
        ],
    },

    # ── A/B Testing ─────────────────────────────────────────────────────────
    "optimizely": {
        "name": "Optimizely",
        "category": "A/B Testing",
        "homepage": "optimizely.com",
        "patterns": [
            r"cdn\.optimizely\.com",
            r"optimizely\.com/js/",
            r"window\.optimizely\b",
        ],
    },
    "launchdarkly": {
        "name": "LaunchDarkly",
        "category": "Feature Flags",
        "homepage": "launchdarkly.com",
        "patterns": [
            r"app\.launchdarkly\.com",
            r"launchdarkly-js",
            r"LDClient\b",
        ],
    },
    "vwo": {
        "name": "VWO",
        "category": "A/B Testing",
        "homepage": "vwo.com",
        "patterns": [
            r"dev\.visualwebsiteoptimizer\.com",
            r"vwo\.com/j/async_visitor_code",
            r"window\._vwo_\b",
        ],
    },

    # ── Monitoring / Error Tracking ──────────────────────────────────────────
    "sentry": {
        "name": "Sentry",
        "category": "Error Tracking",
        "homepage": "sentry.io",
        "patterns": [
            r"browser\.sentry-cdn\.com",
            r"sentry\.io/api/",
            r"Sentry\.init\(",
            r"@sentry/",
        ],
    },
    "datadog": {
        "name": "Datadog RUM",
        "category": "Monitoring",
        "homepage": "datadoghq.com",
        "patterns": [
            r"datadoghq\.com/datadog-rum",
            r"datadoghq-browser-logs",
            r"DD_RUM\b",
        ],
    },
    "bugsnag": {
        "name": "Bugsnag",
        "category": "Error Tracking",
        "homepage": "bugsnag.com",
        "patterns": [
            r"d2wy8f7a9ursnm\.cloudfront\.net",
            r"bugsnag\.start\(",
            r"window\.Bugsnag\b",
        ],
    },
    "new_relic": {
        "name": "New Relic Browser",
        "category": "Monitoring",
        "homepage": "newrelic.com",
        "patterns": [
            r"js-agent\.newrelic\.com",
            r"window\.NREUM\b",
            r"newrelic\.com/assets/",
        ],
    },

    # ── CDN / Infrastructure hints ───────────────────────────────────────────
    "cloudflare": {
        "name": "Cloudflare",
        "category": "CDN / Security",
        "homepage": "cloudflare.com",
        "patterns": [
            r"cloudflare\.com/cdn-cgi/",
            r"challenges\.cloudflare\.com",
            r"cf-ray",
            r"__cf_bm",
        ],
    },
    "vercel": {
        "name": "Vercel",
        "category": "Hosting",
        "homepage": "vercel.com",
        "patterns": [
            r"vercel\.app",
            r"vercel\.com",
            r"_vercel",
            r"VERCEL_",
        ],
    },
    "netlify": {
        "name": "Netlify",
        "category": "Hosting",
        "homepage": "netlify.com",
        "patterns": [
            r"netlify\.app",
            r"netlify\.com",
            r"netlify-cms",
            r"__NETLIFY",
        ],
    },

    # ── CMS / Site builders ──────────────────────────────────────────────────
    "wordpress": {
        "name": "WordPress",
        "category": "CMS",
        "homepage": "wordpress.org",
        "patterns": [
            r"/wp-content/",
            r"/wp-includes/",
            r"wordpress\.org",
            r"wp-json",
        ],
    },
    "webflow": {
        "name": "Webflow",
        "category": "Website Builder",
        "homepage": "webflow.com",
        "patterns": [
            r"webflow\.com/css/",
            r"webflow\.js",
            r"data-wf-",
            r"\.webflow\.io",
        ],
    },
    "shopify": {
        "name": "Shopify",
        "category": "E-Commerce",
        "homepage": "shopify.com",
        "patterns": [
            r"cdn\.shopify\.com",
            r"Shopify\.theme",
            r"shopify\.com/s/files",
            r"myshopify\.com",
        ],
    },
    "framer": {
        "name": "Framer",
        "category": "Website Builder",
        "homepage": "framer.com",
        "patterns": [
            r"framer\.com/m/",
            r"\.framer\.app",
            r"framerusercontent\.com",
        ],
    },

    # ── Video ────────────────────────────────────────────────────────────────
    "wistia": {
        "name": "Wistia",
        "category": "Video",
        "homepage": "wistia.com",
        "patterns": [
            r"fast\.wistia\.(?:net|com)",
            r"wistia_embed",
            r"wistia\.com/medias",
        ],
    },
    "loom": {
        "name": "Loom",
        "category": "Video",
        "homepage": "loom.com",
        "patterns": [
            r"loom\.com/embed/",
            r"loom\.com/share/",
        ],
    },

    # ── Forms / Scheduling ───────────────────────────────────────────────────
    "typeform": {
        "name": "Typeform",
        "category": "Forms",
        "homepage": "typeform.com",
        "patterns": [
            r"typeform\.com/to/",
            r"embed\.typeform\.com",
            r"typeform\.com/embed",
        ],
    },
    "calendly": {
        "name": "Calendly",
        "category": "Scheduling",
        "homepage": "calendly.com",
        "patterns": [
            r"assets\.calendly\.com",
            r"calendly\.com/[a-z0-9-]+/",
            r"Calendly\.initPopupWidget",
        ],
    },

    # ── Customer Feedback ────────────────────────────────────────────────────
    "canny": {
        "name": "Canny",
        "category": "Feedback",
        "homepage": "canny.io",
        "patterns": [
            r"canny\.io/sdk\.js",
            r"Canny\(",
            r"canny-changelog",
        ],
    },
    "uservoice": {
        "name": "UserVoice",
        "category": "Feedback",
        "homepage": "uservoice.com",
        "patterns": [
            r"uservoice\.com/widget",
            r"uservoice\.com/js",
            r"UserVoice\.push",
        ],
    },
}


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

# Pre-compile all patterns for speed
_COMPILED: dict[str, list[re.Pattern]] = {
    tech_id: [re.compile(p, re.IGNORECASE) for p in tech["patterns"]]
    for tech_id, tech in SIGNATURES.items()
}


def scan_html(html: str) -> dict[str, dict]:
    """
    Scan raw HTML text against all built-in signatures.
    Returns dict: {tech_id: {"name", "category", "detected": True, "evidence": "..."}}
    Only includes detected technologies.
    """
    results = {}
    for tech_id, patterns in _COMPILED.items():
        for pattern in patterns:
            m = pattern.search(html)
            if m:
                sig = SIGNATURES[tech_id]
                results[tech_id] = {
                    "name": sig["name"],
                    "category": sig["category"],
                    "detected": True,
                    "evidence": m.group(0)[:80],
                }
                break
    return results


def scan_html_file(path: Path) -> dict[str, dict]:
    """Scan a single raw HTML file. Returns detected technologies."""
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    return scan_html(html)


# ---------------------------------------------------------------------------
# Custom fingerprint generation via Claude
# ---------------------------------------------------------------------------

FINGERPRINT_SYSTEM = (
    "You are a technology detection expert specializing in web stack analysis. "
    "Your job is to extract precise, unique technology fingerprints from raw HTML "
    "that can be used as regex patterns to detect the same technology on other websites. "
    "Focus on non-obvious, proprietary signals — not just obvious script src patterns. "
    "Return only valid JSON."
)

FINGERPRINT_PROMPT = """\
Analyze this raw HTML from a competitor's website and extract technology fingerprints.

<html>
{html}
</html>

Find ALL technologies, tools, vendors, and services used. For each one, generate
precise regex patterns that would detect it on other HTML pages.

Return a JSON array:
[
  {{
    "name": "Technology Name",
    "category": "one of: Analytics | CRM | Payments | Chat | Auth | Framework | CDN | Other",
    "homepage": "vendor URL",
    "patterns": [
      "regex_pattern_1",
      "regex_pattern_2"
    ],
    "confidence": "high | medium | low",
    "evidence": "what you saw in the HTML that led to this detection"
  }}
]

Focus on:
- Script src patterns (especially third-party CDN URLs)
- Window/global variable assignments (window.Foo = ...)
- CSS class prefixes from UI libraries (e.g., chakra-, mantine-, radix-)
- data-* attributes specific to tools
- Meta tags indicating platform
- Inline script configuration patterns
- API keys or IDs embedded in scripts (use regex that matches the format, not the specific value)
- Custom/proprietary class names or patterns specific to this company's vendor choices

Return ONLY the JSON array, no other text.
"""


def generate_custom_fingerprints(html: str, api_key: str = "") -> list[dict]:
    """
    Use Claude to extract custom technology fingerprints from competitor HTML.
    Returns list of {name, category, homepage, patterns, confidence, evidence}.
    """
    try:
        import anthropic
    except ImportError:
        return []

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return []

    # Truncate HTML for context limits
    if len(html) > 60_000:
        html = html[:60_000] + "\n\n[truncated]"

    client = anthropic.Anthropic(api_key=key)
    try:
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=8192,
            system=FINGERPRINT_SYSTEM,
            messages=[{"role": "user", "content": FINGERPRINT_PROMPT.format(html=html)}],
            output_config={"format": {"type": "json_object"}},
        ) as s:
            final = s.get_final_message()
        text = next((b.text for b in final.content if b.type == "text"), "[]")
        result = json.loads(text)
        # Claude may return {"technologies": [...]} or [...]
        if isinstance(result, dict):
            result = result.get("technologies", result.get("fingerprints", []))
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"  [fingerprint] Claude error: {e}", file=sys.stderr)
        return []


def apply_custom_fingerprints(html: str, fingerprints: list[dict]) -> dict[str, dict]:
    """Scan HTML against custom (Claude-generated) fingerprints."""
    results = {}
    for fp in fingerprints:
        name = fp.get("name", "unknown")
        for pattern_str in fp.get("patterns", []):
            try:
                m = re.search(pattern_str, html, re.IGNORECASE)
                if m:
                    results[name] = {
                        "name": name,
                        "category": fp.get("category", "Other"),
                        "detected": True,
                        "evidence": m.group(0)[:80],
                        "source": "custom",
                    }
                    break
            except re.error:
                continue
    return results


# ---------------------------------------------------------------------------
# CLI — scan a single file
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scan an HTML file for technologies.")
    parser.add_argument("file", help="Path to raw HTML file")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    p = Path(args.file)
    if not p.exists():
        sys.exit(f"File not found: {args.file}")

    detected = scan_html_file(p)
    if args.json:
        print(json.dumps(detected, indent=2))
    else:
        if not detected:
            print("No known technologies detected.")
        else:
            by_cat: dict[str, list] = {}
            for tid, t in detected.items():
                by_cat.setdefault(t["category"], []).append(t["name"])
            for cat, names in sorted(by_cat.items()):
                print(f"\n{cat}:")
                for n in names:
                    print(f"  ✓ {n}")
