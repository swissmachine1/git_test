"""Claude-powered GTM content generator for LinkedIn posts."""

import anthropic
from dataclasses import dataclass
from enum import Enum

from config import config


class GTMPostType(str, Enum):
    PRODUCT_LAUNCH = "product_launch"
    FEATURE_ANNOUNCEMENT = "feature_announcement"
    THOUGHT_LEADERSHIP = "thought_leadership"
    CUSTOMER_SUCCESS = "customer_success"
    MARKET_INSIGHT = "market_insight"
    PROBLEM_SOLUTION = "problem_solution"


@dataclass
class GTMPost:
    content: str
    post_type: GTMPostType
    hashtags: list[str]

    @property
    def full_text(self) -> str:
        tags = " ".join(f"#{tag}" for tag in self.hashtags)
        return f"{self.content}\n\n{tags}" if self.hashtags else self.content


SYSTEM_PROMPT = """You are an expert B2B GTM (Go-To-Market) content strategist specializing in LinkedIn.
You craft compelling, professional posts that drive engagement, build brand authority, and generate pipeline.

Your posts follow these principles:
- Hook in the first line (no fluff, straight to value)
- Tell a story or share a specific insight
- Use short paragraphs for readability (1–3 sentences max)
- End with a clear call-to-action or thought-provoking question
- Professional but conversational tone
- Never use excessive emojis (max 1–2 if appropriate)
- LinkedIn character limit: 3,000 characters

Always respond with a JSON object:
{
  "content": "<the post text>",
  "hashtags": ["<tag1>", "<tag2>", "<tag3>"]
}
"""

POST_TYPE_PROMPTS: dict[GTMPostType, str] = {
    GTMPostType.PRODUCT_LAUNCH: """Write a LinkedIn post announcing a new product launch.
Make it exciting but factual. Focus on the problem it solves and the value delivered.
Avoid hype — let the product speak for itself.""",

    GTMPostType.FEATURE_ANNOUNCEMENT: """Write a LinkedIn post announcing a new product feature.
Lead with the customer pain point this feature solves. Use a concrete before/after framing.""",

    GTMPostType.THOUGHT_LEADERSHIP: """Write a LinkedIn thought leadership post about a key trend or challenge
in the industry. Share a non-obvious insight that demonstrates expertise.
Invite the reader to share their perspective.""",

    GTMPostType.CUSTOMER_SUCCESS: """Write a LinkedIn post sharing a customer success story.
Use specific (anonymized) metrics. Follow the structure: Challenge → Solution → Result.""",

    GTMPostType.MARKET_INSIGHT: """Write a LinkedIn post sharing a data-driven market insight relevant
to the target audience. Back it up with a specific stat or observation. Draw an actionable conclusion.""",

    GTMPostType.PROBLEM_SOLUTION: """Write a LinkedIn post using the Problem-Agitate-Solution framework.
Name the problem clearly, make the pain real, then position the product as the solution.""",
}


class ContentGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def generate(
        self,
        post_type: GTMPostType,
        extra_context: str = "",
    ) -> GTMPost:
        """Generate a GTM LinkedIn post using Claude."""
        base_prompt = POST_TYPE_PROMPTS[post_type]

        user_message = f"""{base_prompt}

Company context:
- Company: {config.COMPANY_NAME}
- Product: {config.PRODUCT_NAME}
- Target audience: {config.TARGET_AUDIENCE}
- Industry: {config.INDUSTRY}

{f'Additional context: {extra_context}' if extra_context else ''}

Respond ONLY with a valid JSON object as specified. No markdown, no explanation."""

        with self.client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            response = stream.get_final_message()

        raw = next(
            block.text for block in response.content if block.type == "text"
        )

        import json
        data = json.loads(raw.strip())

        return GTMPost(
            content=data["content"],
            post_type=post_type,
            hashtags=data.get("hashtags", []),
        )
