"""LinkedIn API v2 poster — creates UGC posts on behalf of a member or org."""

import requests
from dataclasses import dataclass

from config import config
from content_generator import GTMPost


LINKEDIN_API_BASE = "https://api.linkedin.com/v2"


@dataclass
class PostResult:
    success: bool
    post_id: str | None = None
    post_url: str | None = None
    error: str | None = None


class LinkedInPoster:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.LINKEDIN_ACCESS_TOKEN}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            }
        )

    def _build_ugc_payload(self, text: str) -> dict:
        return {
            "author": config.author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }

    def post(self, gtm_post: GTMPost) -> PostResult:
        """Publish a GTM post to LinkedIn."""
        payload = self._build_ugc_payload(gtm_post.full_text)
        response = self.session.post(
            f"{LINKEDIN_API_BASE}/ugcPosts", json=payload
        )

        if response.status_code == 201:
            post_id = response.headers.get("x-restli-id", "")
            encoded_id = requests.utils.quote(post_id, safe="")
            post_url = f"https://www.linkedin.com/feed/update/{encoded_id}/"
            return PostResult(success=True, post_id=post_id, post_url=post_url)

        return PostResult(
            success=False,
            error=f"HTTP {response.status_code}: {response.text}",
        )

    def verify_token(self) -> bool:
        """Check that the access token is valid."""
        resp = self.session.get(f"{LINKEDIN_API_BASE}/me")
        return resp.status_code == 200
