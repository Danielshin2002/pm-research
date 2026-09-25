"""Read-only HTTP client with bounded retries and reproducible response caching."""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from senate_market.io import read_json, write_json

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


class PublicClient:
    def __init__(self, cache_dir: Path, *, refresh: bool = False, offline: bool = False):
        if refresh and offline:
            raise ValueError("--refresh and --offline cannot be combined")
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.offline = offline
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers["User-Agent"] = "senate-market-research/0.1"
        self.requests_used: list[dict] = []

    def get(self, base: str, path: str, params: dict):
        url = base + path
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        destination = self.cache_dir / f"{key}.json"
        if destination.exists() and not self.refresh:
            record = read_json(destination)
        else:
            if self.offline:
                raise ValueError(f"No cached response for {url} {params}")
            response = self.session.get(url, params=params, timeout=(10, 45))
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise requests.HTTPError(
                    f"{exc}; API response: {response.text[:500]}", response=response
                ) from exc
            payload = response.json()
            if isinstance(payload, dict) and payload.get("error"):
                raise ValueError(f"API error from {url}: {payload['error']}")
            record = {
                "url": url,
                "params": params,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "payload": payload,
            }
            write_json(destination, record)
            time.sleep(0.1)
        digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        snapshot = self.cache_dir / "responses" / f"{digest}.json"
        if not snapshot.exists():
            write_json(snapshot, record)
        self.requests_used.append(
            {
                "cache_file": str(snapshot),
                "record_sha256": digest,
                "retrieved_at": record["retrieved_at"],
                "url": url,
                "params": params,
            }
        )
        return record["payload"]
