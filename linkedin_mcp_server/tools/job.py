"""
LinkedIn job scraping tools with search and detail extraction.

Uses innerText extraction for resilient job data capture.
"""

import logging
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from linkedin_mcp_server.config.schema import DEFAULT_TOOL_TIMEOUT_SECONDS
from linkedin_mcp_server.core.exceptions import AuthenticationError
from linkedin_mcp_server.tools._job_cache import get_job_cache
from linkedin_mcp_server.dependencies import get_ready_extractor, handle_auth_error
from linkedin_mcp_server.error_handler import raise_tool_error
from linkedin_mcp_server.tools._batch_scrape import batch_scrape_jobs
from linkedin_mcp_server.tools._job_scrape import scrape_job_on_page

logger = logging.getLogger(__name__)


def register_job_tools(
    mcp: FastMCP, *, tool_timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS
) -> None:
    """Register all job-related tools with the MCP server."""

    @mcp.tool(
        timeout=tool_timeout,
        title="Get Job Details",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"job", "scraping"},
        exclude_args=["extractor"],
    )
    async def get_job_details(
        ctx: Context,
        job_id: Annotated[
            str | None,
            Field(
                default=None,
                description="LinkedIn job ID (e.g., '4252026496') for a single job lookup.",
            ),
        ] = None,
        job_ids: Annotated[
            list[str] | None,
            Field(
                default=None,
                description="List of LinkedIn job IDs for batch lookup (e.g., ['4252026496', '3856789012']). Jobs are scraped in parallel.",
            ),
        ] = None,
        refresh: Annotated[
            bool,
            Field(
                default=False,
                description="If True, bypass the job cache and re-scrape from LinkedIn.",
            ),
        ] = False,
        extractor: Any | None = None,
    ) -> dict[str, Any]:
        """
        Get job details for one or more job postings on LinkedIn.

        Provide either ``job_id`` for a single job or ``job_ids`` for batch
        parallel scraping. At least one is required.

        Args:
            ctx: FastMCP context for progress reporting
            job_id: LinkedIn job ID (e.g., "4252026496") for single job lookup.
            job_ids: List of LinkedIn job IDs for batch parallel scraping.

        Returns:
            Single mode: dict with url, sections (name -> raw text), and optional references.
            Batch mode: dict with ``jobs`` (list of per-job results) and top-level metadata.
            The LLM should parse the raw text to extract job details.
        """
        try:
            if refresh:
                job_cache = get_job_cache()
                if job_id:
                    job_cache.invalidate(job_id)
                if job_ids:
                    for jid in job_ids:
                        job_cache.invalidate(jid)

            extractor = extractor or await get_ready_extractor(
                ctx, tool_name="get_job_details"
            )

            # Batch mode
            if job_ids is not None:
                if not job_ids:
                    raise ValueError("job_ids must be a non-empty list")
                if job_id is not None:
                    raise ValueError("Provide either job_id or job_ids, not both")

                logger.info("Batch scraping %d jobs in parallel", len(job_ids))

                await ctx.report_progress(
                    progress=0,
                    total=100,
                    message=f"Starting batch scrape ({len(job_ids)} jobs)",
                )

                all_jobs = await batch_scrape_jobs(extractor.page.context, job_ids)

                logger.debug(
                    "Batch job_details complete: %d jobs, %d with content",
                    len(all_jobs),
                    sum(1 for j in all_jobs if j.get("sections")),
                )

                await ctx.report_progress(
                    progress=100,
                    total=100,
                    message=f"Batch scrape complete ({len(all_jobs)} jobs)",
                )

                return {
                    "jobs": all_jobs,
                    "sections": {},
                    "url": "batch://job_details",
                }

            # Single mode
            if job_id is None:
                raise ValueError("Provide either job_id or job_ids")

            logger.info("Scraping job: %s", job_id)

            await ctx.report_progress(
                progress=0, total=100, message="Starting job scrape"
            )

            result = await scrape_job_on_page(extractor.page, job_id, check_auth=True)

            await ctx.report_progress(progress=100, total=100, message="Complete")

            return result

        except AuthenticationError as e:
            try:
                await handle_auth_error(e, ctx)
            except Exception as relogin_exc:
                raise_tool_error(relogin_exc, "get_job_details")
        except Exception as e:
            raise_tool_error(e, "get_job_details")  # NoReturn

    @mcp.tool(
        timeout=tool_timeout,
        title="Search Jobs",
        annotations={"readOnlyHint": True, "openWorldHint": True},
        tags={"job", "search"},
        exclude_args=["extractor"],
    )
    async def search_jobs(
        keywords: str,
        ctx: Context,
        location: str | None = None,
        max_pages: Annotated[int, Field(ge=1, le=10)] = 3,
        date_posted: str | None = None,
        job_type: str | None = None,
        experience_level: str | None = None,
        work_type: str | None = None,
        easy_apply: bool = False,
        sort_by: str | None = None,
        extractor: Any | None = None,
    ) -> dict[str, Any]:
        """
        Search for jobs on LinkedIn.

        Returns job_ids that can be passed to get_job_details for full info.

        Args:
            keywords: Search keywords (e.g., "software engineer", "data scientist")
            ctx: FastMCP context for progress reporting
            location: Optional location filter (e.g., "San Francisco", "Remote")
            max_pages: Maximum number of result pages to load (1-10, default 3)
            date_posted: Filter by posting date (past_hour, past_24_hours, past_week, past_month)
            job_type: Filter by job type, comma-separated (full_time, part_time, contract, temporary, volunteer, internship, other)
            experience_level: Filter by experience level, comma-separated (internship, entry, associate, mid_senior, director, executive)
            work_type: Filter by work type, comma-separated (on_site, remote, hybrid)
            easy_apply: Only show Easy Apply jobs (default false)
            sort_by: Sort results (date, relevance)

        Returns:
            Dict with url, sections (name -> raw text), job_ids (list of
            numeric job ID strings usable with get_job_details), and optional references.
        """
        try:
            extractor = extractor or await get_ready_extractor(
                ctx, tool_name="search_jobs"
            )
            logger.info(
                "Searching jobs: keywords='%s', location='%s', max_pages=%d",
                keywords,
                location,
                max_pages,
            )

            await ctx.report_progress(
                progress=0, total=100, message="Starting job search"
            )

            result = await extractor.search_jobs(
                keywords,
                location=location,
                max_pages=max_pages,
                date_posted=date_posted,
                job_type=job_type,
                experience_level=experience_level,
                work_type=work_type,
                easy_apply=easy_apply,
                sort_by=sort_by,
            )

            await ctx.report_progress(progress=100, total=100, message="Complete")

            return result

        except AuthenticationError as e:
            try:
                await handle_auth_error(e, ctx)
            except Exception as relogin_exc:
                raise_tool_error(relogin_exc, "search_jobs")
        except Exception as e:
            raise_tool_error(e, "search_jobs")  # NoReturn
