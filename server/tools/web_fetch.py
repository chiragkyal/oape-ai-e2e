"""
Web fetch tool for retrieving URL contents.
"""

import logging
import urllib.request
import urllib.error
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Limits
MAX_RESPONSE_SIZE = 500_000  # 500KB
TIMEOUT = 30  # seconds


@dataclass
class WebResult:
    """Result from fetching a URL."""

    content: str
    status_code: int = 200
    is_error: bool = False


class WebFetchTool:
    """
    Fetch content from URLs.

    Supports HTTP and HTTPS URLs. Used for fetching:
    - GitHub raw content
    - API convention documents
    - Enhancement proposals
    """

    def __init__(self, timeout: int = TIMEOUT):
        self.timeout = timeout

    def execute(self, url: str) -> WebResult:
        """
        Fetch content from a URL.

        Args:
            url: The URL to fetch.

        Returns:
            WebResult with content or error.
        """
        logger.info(f"Fetching URL: {url[:100]}...")

        # Basic URL validation
        if not url.startswith(("http://", "https://")):
            return WebResult(
                content=f"Invalid URL scheme. Must be http:// or https://: {url}",
                status_code=400,
                is_error=True,
            )

        try:
            # Create request with user agent
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "OAPE-Agent/1.0 (OpenShift Operator Development Tool)"
                },
            )

            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                # Check content length
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                    return WebResult(
                        content=f"Response too large: {content_length} bytes. "
                        f"Max: {MAX_RESPONSE_SIZE} bytes.",
                        status_code=413,
                        is_error=True,
                    )

                # Read content
                content = response.read(MAX_RESPONSE_SIZE)

                # Try to decode as text
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError:
                    text = content.decode("latin-1")

                return WebResult(content=text, status_code=response.status)

        except urllib.error.HTTPError as e:
            logger.warning(f"HTTP error fetching {url}: {e.code}")
            return WebResult(
                content=f"HTTP {e.code}: {e.reason}",
                status_code=e.code,
                is_error=True,
            )

        except urllib.error.URLError as e:
            logger.error(f"URL error fetching {url}: {e.reason}")
            return WebResult(
                content=f"URL error: {str(e.reason)}",
                status_code=0,
                is_error=True,
            )

        except TimeoutError:
            logger.warning(f"Timeout fetching {url}")
            return WebResult(
                content=f"Request timed out after {self.timeout} seconds",
                status_code=408,
                is_error=True,
            )

        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return WebResult(
                content=f"Fetch error: {str(e)}",
                status_code=500,
                is_error=True,
            )

