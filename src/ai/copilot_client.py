"""
GitHub Copilot API client for PII detection with retry logic and caching.

This module provides integration with the GitHub Copilot Model API for automated
PII detection in database schemas. Features include exponential backoff retry,
response caching, and graceful error handling.

Author: Database Sanitization Team
Date: 2026-03-26
"""

import hashlib
import json
import os
import time
from functools import wraps
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path

import requests
from requests import Session, Response
from requests.exceptions import (
    ConnectionError,
    Timeout,
    RequestException,
)
from pydantic import ValidationError

from .models import PIIColumn, PIIDetectionResponse
from .prompts import build_pii_detection_prompt, build_large_schema_prompt
from ..exceptions import APIRequestError, APIResponseError
from ..logging.logger import get_logger
from ..logging.correlation import CorrelationContext


def retry_on_api_error(
    max_attempts: int = 3,
    backoff_factor: float = 1.0,
    retryable_status_codes: Optional[List[int]] = None
) -> Callable:
    """
    Decorator for retrying API requests with exponential backoff.
    
    Automatically retries on:
    - Timeouts
    - Connection errors
    - Server errors (500, 502, 503, 504)
    - Rate limits (429) with respect to Retry-After header
    
    Does NOT retry on:
    - Authentication failures (401, 403)
    - Client errors (400, 404, etc.)
    
    Args:
        max_attempts: Maximum retry attempts (default: 3)
        backoff_factor: Exponential backoff multiplier (default: 1.0)
        retryable_status_codes: Additional HTTP status codes to retry
    
    Returns:
        Decorated function with retry logic
    
    Example:
        >>> @retry_on_api_error(max_attempts=5, backoff_factor=0.5)
        ... def make_request():
        ...     return requests.post(url, json=payload)
    """
    if retryable_status_codes is None:
        retryable_status_codes = [500, 502, 503, 504, 429]
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = get_logger(__name__)
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                
                except Timeout as e:
                    last_exception = e
                    if attempt == max_attempts:
                        raise APIRequestError.api_timeout(
                            timeout_seconds=kwargs.get("timeout", 30)
                        ) from e
                    
                    delay = backoff_factor * (2 ** (attempt - 1))
                    logger.warning(
                        f"Request timeout (attempt {attempt}/{max_attempts}). "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                
                except ConnectionError as e:
                    last_exception = e
                    if attempt == max_attempts:
                        raise APIRequestError.network_error(
                            reason=str(e)
                        ) from e
                    
                    delay = backoff_factor * (2 ** (attempt - 1))
                    logger.warning(
                        f"Connection error (attempt {attempt}/{max_attempts}). "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                
                except RequestException as e:
                    # Check if it's an HTTP error with retryable status code
                    if hasattr(e, 'response') and e.response is not None:
                        status_code = e.response.status_code
                        
                        # Handle rate limiting with Retry-After header
                        if status_code == 429:
                            retry_after = e.response.headers.get('Retry-After')
                            if retry_after:
                                try:
                                    delay = int(retry_after)
                                except ValueError:
                                    delay = backoff_factor * (2 ** (attempt - 1))
                            else:
                                delay = backoff_factor * (2 ** (attempt - 1))
                            
                            if attempt == max_attempts:
                                raise APIRequestError.api_quota_exceeded(
                                    retry_after=delay
                                ) from e
                            
                            logger.warning(
                                f"Rate limit exceeded (attempt {attempt}/{max_attempts}). "
                                f"Retrying in {delay}s..."
                            )
                            time.sleep(delay)
                            continue
                        
                        # Retry on server errors
                        if status_code in retryable_status_codes:
                            if attempt == max_attempts:
                                raise APIRequestError.api_request_failed(
                                    reason=str(e),
                                    status_code=status_code
                                ) from e
                            
                            delay = backoff_factor * (2 ** (attempt - 1))
                            logger.warning(
                                f"Server error {status_code} (attempt {attempt}/{max_attempts}). "
                                f"Retrying in {delay}s..."
                            )
                            time.sleep(delay)
                            continue
                        
                        # Don't retry on auth errors or client errors
                        if status_code in [401, 403]:
                            raise APIRequestError.authentication_failed(
                                reason=f"HTTP {status_code}: {str(e)}"
                            ) from e
                        else:
                            raise APIRequestError.api_request_failed(
                                reason=str(e),
                                status_code=status_code
                            ) from e
                    
                    # Unknown request exception
                    last_exception = e
                    raise APIRequestError.api_request_failed(
                        reason=str(e)
                    ) from e
            
            # Should never reach here, but satisfy type checker
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


class CopilotClient:
    """
    GitHub Copilot API client for automated PII detection.
    
    This client sends database schema metadata to the GitHub Copilot Model API
    and receives structured recommendations for columns likely containing PII.
    Features include automatic retry with exponential backoff, response caching,
    and batch processing for large schemas.
    
    Attributes:
        api_url: GitHub Copilot API endpoint
        api_key: API authentication key (from environment variable)
        timeout: Request timeout in seconds
        max_retries: Maximum retry attempts
        backoff_factor: Exponential backoff multiplier
        cache_enabled: Whether response caching is enabled
        cache_ttl_hours: Cache time-to-live in hours
        max_tables_per_request: Maximum tables per API request
        max_schema_size: Maximum schema size in characters
        session: Requests session for connection pooling
        cache_dir: Cache directory path
        logger: Logger with context
    
    Example:
        >>> from src.ai import CopilotClient
        >>> from src.config import AIConfig
        >>> 
        >>> config = AIConfig(
        ...     api_url="https://api.github.com/copilot/model",
        ...     timeout_seconds=60
        ... )
        >>> client = CopilotClient(config)
        >>> 
        >>> schema = schema_extractor.extract_schema("database")
        >>> pii_columns = client.detect_pii(schema)
        >>> for col in pii_columns:
        ...     print(f"{col.schema}.{col.table}.{col.column}: {col.pii_type}")
    """
    
    def __init__(
        self,
        api_url: str = "https://models.github.ai/inference/chat/completions",
        api_key_env_var: str = "GITHUB_COPILOT_TOKEN",
        model: str = "gpt-4o",
        timeout_seconds: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        cache_enabled: bool = True,
        cache_ttl_hours: int = 24,
        max_tables_per_request: int = 50,
        max_schema_size_chars: int = 50000,
        logger: Optional[Any] = None,
    ) -> None:
        """
        Initialize the CopilotClient.
        
        Args:
            api_url: GitHub Models API endpoint URL (default: https://models.github.ai)
            api_key_env_var: Environment variable name containing API key
            model: Model name to use (default: gpt-4o)
            timeout_seconds: Request timeout in seconds
            max_retries: Maximum retry attempts for failed requests
            backoff_factor: Exponential backoff multiplier
            cache_enabled: Whether to cache API responses
            cache_ttl_hours: Cache time-to-live in hours
            max_tables_per_request: Maximum tables to send in one request
            max_schema_size_chars: Maximum schema size in characters
            logger: Optional logger with context
        
        Raises:
            APIRequestError: If API key not found in environment
        """
        self.api_url = api_url
        self.api_key_env_var = api_key_env_var
        self.model = model
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.cache_enabled = cache_enabled
        self.cache_ttl_hours = cache_ttl_hours
        self.max_tables_per_request = max_tables_per_request
        self.max_schema_size = max_schema_size_chars
        self.logger = logger or get_logger(__name__).with_context(module="copilot_client")
        
        # Get API key from environment
        self.api_key = os.getenv(api_key_env_var)
        if not self.api_key:
            self.logger.warning(
                f"API key not found in environment variable '{api_key_env_var}'. "
                "AI-powered PII detection will not be available."
            )
        
        # Initialize requests session for connection pooling
        self.session = Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "Database-Sanitization-Framework/1.0"
        })
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}"
            })
        
        # Setup cache directory
        self.cache_dir = Path.home() / ".cache" / "db-sanitization"
        if self.cache_enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Cache directory: {self.cache_dir}")
    
    def detect_pii(
        self,
        schema_metadata: Dict[str, Any],
    ) -> List[PIIColumn]:
        """
        Detect PII columns in database schema using AI.
        
        This is the main entry point for PII detection. It automatically:
        - Checks cache for previous results
        - Splits large schemas into batches
        - Builds appropriate prompts
        - Makes API requests with retry logic
        - Validates and parses responses
        - Caches results for future use
        
        Args:
            schema_metadata: Schema information from SchemaExtractor
                            Expected keys: "tables" with array of table objects
        
        Returns:
            List of PIIColumn instances representing detected PII
        
        Raises:
            APIRequestError: If API request fails after all retries
            APIResponseError: If response parsing or validation fails
        
        Example:
            >>> schema = {"tables": [...]}
            >>> pii_columns = client.detect_pii(schema)
            >>> print(f"Found {len(pii_columns)} PII columns")
        """
        with CorrelationContext() as correlation_id:
            self.logger.info(
                "Starting PII detection",
                extra={"correlation_id": correlation_id}
            )
            
            # Check if API key is available
            if not self.api_key:
                self.logger.warning(
                    "API key not configured. Returning empty PII column list.",
                    extra={"correlation_id": correlation_id}
                )
                return []
            
            # Check cache first
            cache_key = self._generate_cache_key(schema_metadata)
            if self.cache_enabled:
                cached_result = self._get_cached_response(cache_key)
                if cached_result is not None:
                    self.logger.info(
                        f"Cache hit: returning {len(cached_result)} PII columns from cache",
                        extra={"correlation_id": correlation_id}
                    )
                    return cached_result
            
            # Check schema size
            schema_json = json.dumps(schema_metadata, ensure_ascii=False)
            schema_size = len(schema_json)
            
            # If schema is too large, process in batches
            if schema_size > self.max_schema_size:
                self.logger.info(
                    f"Schema size ({schema_size} chars) exceeds limit ({self.max_schema_size}). "
                    f"Processing in batches...",
                    extra={"correlation_id": correlation_id}
                )
                pii_columns = self._detect_pii_batched(schema_metadata, correlation_id)
            else:
                self.logger.info(
                    f"Processing schema ({schema_size} chars)",
                    extra={"correlation_id": correlation_id}
                )
                pii_columns = self._detect_pii_single(schema_metadata, correlation_id)
            
            # Cache the result
            if self.cache_enabled:
                self._cache_response(cache_key, pii_columns)
            
            self.logger.info(
                f"PII detection complete: found {len(pii_columns)} PII columns",
                extra={"correlation_id": correlation_id}
            )
            
            return pii_columns
    
    def _detect_pii_single(
        self,
        schema_metadata: Dict[str, Any],
        correlation_id: str
    ) -> List[PIIColumn]:
        """
        Detect PII in single API request.
        
        Args:
            schema_metadata: Complete schema metadata
            correlation_id: Correlation ID for logging
        
        Returns:
            List of detected PIIColumn instances
        """
        # Build prompt
        prompts = build_pii_detection_prompt(schema_metadata)
        
        # Make API request
        response = self._make_api_request(prompts, correlation_id)
        
        # Parse and validate response
        pii_columns = self._parse_response(response, correlation_id)
        
        return pii_columns
    
    def _detect_pii_batched(
        self,
        schema_metadata: Dict[str, Any],
        correlation_id: str
    ) -> List[PIIColumn]:
        """
        Detect PII by processing schema in batches.
        
        Args:
            schema_metadata: Complete schema metadata
            correlation_id: Correlation ID for logging
        
        Returns:
            Merged list of PII columns from all batches
        """
        tables = schema_metadata.get("tables", [])
        total_tables = len(tables)
        batch_size = self.max_tables_per_request
        
        all_pii_columns: List[PIIColumn] = []
        
        # Process in batches
        for i in range(0, total_tables, batch_size):
            batch_number = (i // batch_size) + 1
            total_batches = (total_tables + batch_size - 1) // batch_size
            
            batch_tables = tables[i:i + batch_size]
            batch_metadata = {
                "database": schema_metadata.get("database"),
                "tables": batch_tables
            }
            
            self.logger.info(
                f"Processing batch {batch_number}/{total_batches} "
                f"({len(batch_tables)} tables)",
                extra={"correlation_id": correlation_id}
            )
            
            # Build batch prompt
            prompts = build_large_schema_prompt(
                batch_metadata,
                batch_number,
                total_batches
            )
            
            # Make API request
            response = self._make_api_request(prompts, correlation_id)
            
            # Parse and merge results
            batch_pii_columns = self._parse_response(response, correlation_id)
            all_pii_columns.extend(batch_pii_columns)
        
        # Deduplicate across batches
        deduplicated = self._deduplicate_pii_columns(all_pii_columns)
        
        self.logger.info(
            f"Merged {len(all_pii_columns)} PII columns from {total_batches} batches "
            f"({len(deduplicated)} after deduplication)",
            extra={"correlation_id": correlation_id}
        )
        
        return deduplicated
    
    @retry_on_api_error(max_attempts=3, backoff_factor=1.0)
    def _make_api_request(
        self,
        prompts: Dict[str, str],
        correlation_id: str
    ) -> Response:
        """
        Make API request to GitHub Copilot Model API.
        
        Args:
            prompts: Dictionary with "system" and "user" prompt strings
            correlation_id: Correlation ID for logging
        
        Returns:
            Response object from requests library
        
        Raises:
            APIRequestError: If request fails (raised by retry decorator)
        """
        payload = {
            "messages": [
                {"role": "system", "content": prompts["system"]},
                {"role": "user", "content": prompts["user"]}
            ],
            "model": self.model,  # Use configured model (e.g., gpt-4o)
            "temperature": 0.0,  # Deterministic responses
            "max_tokens": 4000
        }
        
        self.logger.debug(
            f"Making API request to {self.api_url} with model {self.model}",
            extra={"correlation_id": correlation_id}
        )
        
        response = self.session.post(
            self.api_url,
            json=payload,
            timeout=self.timeout
        )
        
        # Raise for HTTP errors (4xx, 5xx)
        response.raise_for_status()
        
        self.logger.debug(
            f"API request successful (HTTP {response.status_code})",
            extra={"correlation_id": correlation_id}
        )
        
        return response
    
    def _parse_response(
        self,
        response: Response,
        correlation_id: str
    ) -> List[PIIColumn]:
        """
        Parse and validate API response.
        
        Args:
            response: Response object from requests
            correlation_id: Correlation ID for logging
        
        Returns:
            List of validated PIIColumn instances
        
        Raises:
            APIResponseError: If parsing or validation fails
        """
        try:
            response_json = response.json()
        except json.JSONDecodeError as e:
            raise APIResponseError.parsing_failed(
                reason=f"Invalid JSON: {str(e)}",
                response_preview=response.text[:200]
            ) from e
        
        # Extract content from response
        # Adjust this based on actual API response structure
        try:
            # Assuming response has structure: {"choices": [{"message": {"content": "..."}}]}
            content = response_json.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if not content:
                raise APIResponseError.invalid_response(
                    reason="Empty response content",
                    response_preview=json.dumps(response_json)[:200]
                )
            
            # Parse the content as JSON
            pii_data = json.loads(content)
            
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise APIResponseError.parsing_failed(
                reason=f"Failed to extract PII data: {str(e)}",
                response_preview=json.dumps(response_json)[:200]
            ) from e
        
        # Validate with Pydantic
        try:
            detection_response = PIIDetectionResponse(**pii_data)
        except ValidationError as e:
            raise APIResponseError.parsing_failed(
                reason=f"Response validation failed: {str(e)}",
                response_preview=json.dumps(pii_data)[:200]
            ) from e
        
        self.logger.info(
            f"Parsed {len(detection_response.pii_columns)} PII columns from response",
            extra={"correlation_id": correlation_id}
        )
        
        return detection_response.pii_columns
    
    def _generate_cache_key(self, schema_metadata: Dict[str, Any]) -> str:
        """
        Generate deterministic cache key from schema metadata.
        
        Args:
            schema_metadata: Schema metadata dictionary
        
        Returns:
            SHA256 hash of schema metadata as hex string
        """
        # Sort keys for deterministic JSON serialization
        schema_json = json.dumps(schema_metadata, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(schema_json.encode('utf-8')).hexdigest()
    
    def _get_cached_response(self, cache_key: str) -> Optional[List[PIIColumn]]:
        """
        Retrieve cached response if available and not expired.
        
        Args:
            cache_key: Cache key (SHA256 hash)
        
        Returns:
            List of PIIColumn instances if cache hit, None otherwise
        """
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        if not cache_file.exists():
            return None
        
        # Check if cache is expired
        cache_age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if cache_age_hours > self.cache_ttl_hours:
            self.logger.debug(f"Cache expired ({cache_age_hours:.1f}h old)")
            cache_file.unlink()  # Delete expired cache
            return None
        
        # Load and deserialize
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Reconstruct PIIColumn instances
            pii_columns = [PIIColumn(**col_data) for col_data in data]
            
            return pii_columns
        
        except (json.JSONDecodeError, ValidationError, IOError) as e:
            self.logger.warning(f"Failed to load cache: {str(e)}")
            return None
    
    def _cache_response(self, cache_key: str, pii_columns: List[PIIColumn]) -> None:
        """
        Cache API response for future use.
        
        Args:
            cache_key: Cache key (SHA256 hash)
            pii_columns: List of PIIColumn instances to cache
        """
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        try:
            # Serialize PIIColumn instances
            data = [col.model_dump() for col in pii_columns]
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.logger.debug(f"Cached {len(pii_columns)} PII columns")
        
        except IOError as e:
            self.logger.warning(f"Failed to cache response: {str(e)}")
    
    def clear_cache(self) -> int:
        """
        Clear all cached API responses.
        
        Returns:
            Number of cache files deleted
        """
        if not self.cache_dir.exists():
            return 0
        
        deleted_count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                deleted_count += 1
            except IOError:
                pass
        
        self.logger.info(f"Cleared {deleted_count} cache files")
        return deleted_count
    
    def _deduplicate_pii_columns(self, pii_columns: List[PIIColumn]) -> List[PIIColumn]:
        """
        Remove duplicate PII columns from list.
        
        Args:
            pii_columns: List of PIIColumn instances (may contain duplicates)
        
        Returns:
            Deduplicated list (preserves first occurrence)
        """
        seen = set()
        deduplicated = []
        
        for col in pii_columns:
            if col not in seen:
                seen.add(col)
                deduplicated.append(col)
        
        return deduplicated
    
    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"CopilotClient(api_url={self.api_url!r}, timeout={self.timeout}s, "
            f"cache_enabled={self.cache_enabled})"
        )
