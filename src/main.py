"""
LinkedIn GTM Auto-Poster
========================
Generate and publish Go-To-Market content on LinkedIn using Claude AI.

Usage:
  # Post once (interactive mode — preview before publishing)
  python src/main.py --type thought_leadership

  # Post immediately without preview
  python src/main.py --type product_launch --no-preview

  # Post with extra context
  python src/main.py --type feature_announcement --context "We just shipped dark mode"

  # Run the scheduler (posts daily at 9am)
  python src/main.py --schedule

  # List available post types
  python src/main.py --list-types
"""

import argparse
import sys
import schedule
import time
import random
from datetime import datetime

from config import config
from content_generator import ContentGenerator, GTMPostType
from linkedin_poster import LinkedInPoster


def generate_and_post(
    post_type: GTMPostType,
    extra_context: str = "",
    preview: bool = True,
    dry_run: bool = False,
) -> bool:
    """Generate a post with Claude and publish it to LinkedIn."""
    generator = ContentGenerator()
    poster = LinkedInPoster()

    print(f"\n[{datetime.now():%Y-%m-%d %H:%M}] Generating {post_type.value} post...")
    post = generator.generate(post_type, extra_context)

    print("\n" + "=" * 60)
    print("GENERATED POST")
    print("=" * 60)
    print(post.full_text)
    print(f"\nCharacters: {len(post.full_text)} / 3000")
    print("=" * 60)

    if dry_run:
        print("\n[DRY RUN] Post not published.")
        return True

    if preview:
        answer = input("\nPublish this post? [y/N] ").strip().lower()
        if answer != "y":
            print("Cancelled.")
            return False

    print("\nPublishing to LinkedIn...")
    result = poster.post(post)

    if result.success:
        print(f"✓ Published! View at: {result.post_url}")
        return True
    else:
        print(f"✗ Failed to publish: {result.error}")
        return False


def run_scheduler(post_time: str = "09:00"):
    """Run the auto-poster on a daily schedule."""
    poster = LinkedInPoster()

    if not poster.verify_token():
        print("ERROR: LinkedIn access token is invalid. Please check your .env file.")
        sys.exit(1)

    post_types = list(GTMPostType)

    def scheduled_post():
        post_type = random.choice(post_types)
        print(f"\n[Scheduler] Running scheduled post — type: {post_type.value}")
        generate_and_post(post_type, preview=False)

    schedule.every().day.at(post_time).do(scheduled_post)
    print(f"Scheduler started. Posts will be published daily at {post_time}.")
    print("Press Ctrl+C to stop.\n")

    while True:
        schedule.run_pending()
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(
        description="Auto-post GTM content to LinkedIn using Claude AI"
    )
    parser.add_argument(
        "--type",
        choices=[t.value for t in GTMPostType],
        default=GTMPostType.THOUGHT_LEADERSHIP.value,
        help="Type of GTM post to generate",
    )
    parser.add_argument(
        "--context",
        default="",
        help="Additional context to guide content generation",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Publish immediately without preview prompt",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate content but do not publish",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Run as a daily scheduler",
    )
    parser.add_argument(
        "--schedule-time",
        default="09:00",
        help="Time to post daily when using --schedule (24h format, e.g. 09:00)",
    )
    parser.add_argument(
        "--list-types",
        action="store_true",
        help="List all available post types and exit",
    )

    args = parser.parse_args()

    if args.list_types:
        print("\nAvailable GTM post types:")
        for t in GTMPostType:
            print(f"  {t.value}")
        return

    if args.schedule:
        run_scheduler(args.schedule_time)
        return

    generate_and_post(
        post_type=GTMPostType(args.type),
        extra_context=args.context,
        preview=not args.no_preview,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
