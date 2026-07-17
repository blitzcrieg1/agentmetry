"""Agentmetry forward sinks — file, webhook, Elastic ECS, Splunk HEC."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from threading import Lock
from typing import Any

import httpx

from core.audit.adapters.ecs import canonical_to_ecs
from core.audit.adapters.splunk import canonical_to_hec_event

logger = logging.getLogger(__name__)

_file_lock = Lock()


class AuditSink(ABC):
    @abstractmethod
    async def emit(self, canonical: dict[str, Any]) -> None:
        ...


class FileAuditSink(AuditSink):
    def __init__(self, path: Path) -> None:
        self._path = path

    async def emit(self, canonical: dict[str, Any]) -> None:
        from core.audit.trail_chain import append_chained_line

        with _file_lock:
            append_chained_line(self._path, canonical)


class WebhookAuditSink(AuditSink):
    def __init__(self, url: str, *, timeout_seconds: float = 5.0) -> None:
        self._url = url
        self._timeout = timeout_seconds

    async def emit(self, canonical: dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url,
                    json=canonical,
                    headers={"Content-Type": "application/json", "User-Agent": "Agentmetry/1.0"},
                )
                response.raise_for_status()
        except Exception:
            logger.exception("Audit webhook POST failed → %s", self._url)


class ElasticEcsSink(AuditSink):
    """Index one ECS document per event (Elasticsearch _doc API)."""

    def __init__(
        self,
        base_url: str,
        index: str,
        api_key: str,
        *,
        timeout_seconds: float = 5.0,
        verify_tls: bool = True,
    ) -> None:
        self._url = base_url.rstrip("/") + f"/{index}/_doc"
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._verify = verify_tls

    async def emit(self, canonical: dict[str, Any]) -> None:
        doc = canonical_to_ecs(canonical)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"ApiKey {self._api_key}",
            "User-Agent": "Agentmetry/1.0",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, verify=self._verify) as client:
                response = await client.post(self._url, json=doc, headers=headers)
                response.raise_for_status()
        except Exception:
            logger.exception("Elastic ECS index failed → %s", self._url)


class SplunkHecSink(AuditSink):
    """POST one event to Splunk HTTP Event Collector."""

    def __init__(
        self,
        hec_url: str,
        token: str,
        *,
        index: str = "main",
        sourcetype: str = "agentmetry:json",
        timeout_seconds: float = 5.0,
        verify_tls: bool = True,
    ) -> None:
        base = hec_url.rstrip("/")
        if base.endswith("/services/collector"):
            self._url = base
        elif base.endswith("/services/collector/event"):
            self._url = base
        else:
            self._url = base + "/services/collector/event"
        self._token = token
        self._index = index
        self._sourcetype = sourcetype
        self._timeout = timeout_seconds
        self._verify = verify_tls

    async def emit(self, canonical: dict[str, Any]) -> None:
        payload = canonical_to_hec_event(
            canonical,
            index=self._index,
            sourcetype=self._sourcetype,
        )
        headers = {
            "Authorization": f"Splunk {self._token}",
            "Content-Type": "application/json",
            "User-Agent": "Agentmetry/1.0",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, verify=self._verify) as client:
                response = await client.post(self._url, json=payload, headers=headers)
                response.raise_for_status()
        except Exception:
            logger.exception("Splunk HEC POST failed → %s", self._url)


class MultiAuditSink(AuditSink):
    def __init__(self, sinks: list[AuditSink]) -> None:
        self._sinks = sinks

    async def emit(self, canonical: dict[str, Any]) -> None:
        for sink in self._sinks:
            await sink.emit(canonical)


def parse_sink_modes(raw: str) -> set[str]:
    text = raw.strip().lower()
    if not text or text == "file":
        return {"file"}
    if text == "both":
        return {"file", "webhook"}
    if text == "all":
        return {"file", "webhook", "elastic", "splunk"}
    return {part.strip() for part in text.split(",") if part.strip()}


def build_audit_sinks(
    *,
    modes: set[str],
    file_path: Path,
    webhook_url: str,
    webhook_timeout_seconds: float,
    elastic_url: str,
    elastic_index: str,
    elastic_api_key: str,
    elastic_verify_tls: bool,
    splunk_hec_url: str,
    splunk_hec_token: str,
    splunk_index: str,
    splunk_sourcetype: str,
    splunk_verify_tls: bool,
) -> AuditSink | None:
    sinks: list[AuditSink] = []

    if "file" in modes:
        sinks.append(FileAuditSink(file_path))

    if "webhook" in modes and webhook_url.strip():
        sinks.append(WebhookAuditSink(webhook_url.strip(), timeout_seconds=webhook_timeout_seconds))

    if "elastic" in modes and elastic_url.strip() and elastic_api_key.strip():
        sinks.append(
            ElasticEcsSink(
                elastic_url.strip(),
                elastic_index,
                elastic_api_key.strip(),
                timeout_seconds=webhook_timeout_seconds,
                verify_tls=elastic_verify_tls,
            )
        )

    if "splunk" in modes and splunk_hec_url.strip() and splunk_hec_token.strip():
        sinks.append(
            SplunkHecSink(
                splunk_hec_url.strip(),
                splunk_hec_token.strip(),
                index=splunk_index,
                sourcetype=splunk_sourcetype,
                timeout_seconds=webhook_timeout_seconds,
                verify_tls=splunk_verify_tls,
            )
        )

    if not sinks:
        return None
    if len(sinks) == 1:
        return sinks[0]
    return MultiAuditSink(sinks)
