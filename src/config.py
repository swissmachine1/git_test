"""Configuration loader for LinkedIn GTM Auto-Poster."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Anthropic
    ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]

    # LinkedIn
    LINKEDIN_ACCESS_TOKEN: str = os.environ["LINKEDIN_ACCESS_TOKEN"]
    LINKEDIN_PERSON_URN: str = os.environ["LINKEDIN_PERSON_URN"]
    LINKEDIN_ORG_URN: str | None = os.getenv("LINKEDIN_ORG_URN")

    # GTM context
    COMPANY_NAME: str = os.getenv("COMPANY_NAME", "Our Company")
    PRODUCT_NAME: str = os.getenv("PRODUCT_NAME", "Our Product")
    TARGET_AUDIENCE: str = os.getenv("TARGET_AUDIENCE", "business professionals")
    INDUSTRY: str = os.getenv("INDUSTRY", "Technology")

    @property
    def author_urn(self) -> str:
        """Returns org URN if available, else person URN."""
        return self.LINKEDIN_ORG_URN or self.LINKEDIN_PERSON_URN


config = Config()
