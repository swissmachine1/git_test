This is Augustin's first git project!

# LinkedIn GTM Auto-Poster

Automatically generate and publish Go-To-Market content on LinkedIn using Claude AI (claude-opus-4-6).

## How it works

1. **Claude generates** a LinkedIn post tailored to your product and audience
2. **You review** the post (or skip the preview with `--no-preview`)
3. **The post is published** via the LinkedIn UGC Posts API

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

You need:
- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com)
- `LINKEDIN_ACCESS_TOKEN` — from your [LinkedIn Developer App](https://www.linkedin.com/developers/apps) (scope: `w_member_social`)
- `LINKEDIN_PERSON_URN` — your LinkedIn member URN (see below)

**Getting your Person URN:**
```bash
curl -H "Authorization: Bearer <your_token>" https://api.linkedin.com/v2/me
# Look for the "id" field, then format as: urn:li:person:<id>
```

### 3. Run

```bash
# Generate and preview a post (interactive)
python src/main.py --type thought_leadership

# Post immediately without preview
python src/main.py --type product_launch --no-preview

# Add specific context
python src/main.py --type feature_announcement --context "We just launched SSO support"

# Dry run (generate only, no publishing)
python src/main.py --type market_insight --dry-run

# Daily scheduler at 9am
python src/main.py --schedule --schedule-time 09:00
```

## Post Types

| Type | Description |
|------|-------------|
| `thought_leadership` | Industry insight or non-obvious take |
| `product_launch` | New product announcement |
| `feature_announcement` | New feature with before/after framing |
| `customer_success` | Challenge → Solution → Result story |
| `market_insight` | Data-driven market observation |
| `problem_solution` | Problem-Agitate-Solution framework |

## Project Structure

```
src/
  config.py            # Environment variable loader
  content_generator.py # Claude API — generates GTM posts
  linkedin_poster.py   # LinkedIn API v2 — publishes posts
  main.py              # CLI entry point + scheduler
requirements.txt
.env.example
```
