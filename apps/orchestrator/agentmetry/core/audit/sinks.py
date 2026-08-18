"""Agentmetry forward sinks — file, webhook, Elastic ECS, Splunk HEC."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from threading import Lock
from typing import Any

import httpx

from agentmetry.core.audit.adapters.ecs import canonical_to_ecs
from agentmetry.core.audit.adapters.chronicle import canonical_to_udm_batch
from agentmetry.core.audit.adapters.splunk import canonical_to_hec_event

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
        from agentmetry.core.audit.trail_chain import append_chained_line

        with _file_lock:
            append_chained_line(self._path, canonical)


class WebhookAuditSink(AuditSink):
    """POST each event to a URL, as the canonical record or a CloudEvent.

    `format="cloudevents"` wraps the same record in a CloudEvents v1.0 structured
    envelope, which is what brokers speak: Knative, EventBridge, Event Grid,
    Dapr and the Kafka bindings all consume it. The canonical event still travels
    whole inside `data`, so nothing is lost by choosing it.

    Default stays `canonical`. Changing the shape of what an existing webhook
    receives because a new option appeared would break every consumer already
    wired up, and silently.
    """

    def __init__(
        self, url: str, *, timeout_seconds: float = 5.0, format: str = "canonical"
    ) -> None:
        self._url = url
        self._timeout = timeout_seconds
        self._cloudevents = (format or "").strip().lower() in ("cloudevents", "cloudevent", "ce")

    async def emit(self, canonical: dict[str, Any]) -> None:
        payload = canonical
        # `application/cloudevents+json` is what marks structured mode; a
        # consumer distinguishes it from a bare JSON body by content type alone.
        content_type = "application/json"
        if self._cloudevents:
            from agentmetry.core.audit.adapters.cloudevents import canonical_to_cloudevent

            payload = canonical_to_cloudevent(canonical)
            content_type = "application/cloudevents+json; charset=utf-8"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url,
                    json=payload,
                    headers={"Content-Type": content_type, "User-Agent": "Agentmetry/1.0"},
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


class ChronicleUdmSink(AuditSink):
    """POST one UDM event to the Google SecOps ingestion API.

    Posts to `udmevents` rather than `unstructuredlogentries`, so Chronicle
    stores what we send instead of running it through a Config Based
    Normalization parser we would then have to maintain in the customer's tenant.
    See adapters/chronicle.py for why that trade is worth making.

    ## Authentication, and an honest limitation

    Chronicle ingestion is OAuth2 against a Google service account. Two paths:

    * a service account JSON file, when `google-auth` is installed, which
      refreshes automatically and is the only option suitable for a long-running
      forwarder;
    * a static bearer token, which needs no extra dependency and **expires**,
      typically within the hour.

    `google-auth` is deliberately not a hard dependency of the open-source core:
    a local recorder for one developer should not pull Google's auth stack to run.
    So the static token stays available and this class says plainly, once, that it
    will stop working. A forwarder that silently stopped forwarding after fifty
    minutes would be a worse failure than refusing to start.
    """

    _warned_static = False

    def __init__(
        self,
        endpoint: str,
        customer_id: str,
        *,
        service_account_file: str = "",
        bearer_token: str = "",
        timeout_seconds: float = 5.0,
        verify_tls: bool = True,
    ) -> None:
        self._url = endpoint.rstrip("/")
        self._customer_id = customer_id
        self._timeout = timeout_seconds
        self._verify = verify_tls
        self._bearer = bearer_token
        self._credentials = None

        if service_account_file:
            try:
                from google.auth.transport.requests import Request  # noqa: F401
                from google.oauth2 import service_account

                self._credentials = service_account.Credentials.from_service_account_file(
                    service_account_file,
                    scopes=["https://www.googleapis.com/auth/malachite-ingestion"],
                )
            except ImportError:
                logger.error(
                    "AGENTMETRY_CHRONICLE_SERVICE_ACCOUNT is set but google-auth is not "
                    "installed. Install it (pip install google-auth) or supply a bearer "
                    "token; Chronicle forwarding is disabled until one of those is true."
                )
            except Exception:
                logger.exception("Could not load Chronicle service account credentials")
        elif bearer_token and not ChronicleUdmSink._warned_static:
            ChronicleUdmSink._warned_static = True
            logger.warning(
                "Chronicle sink is using a static bearer token, which expires "
                "(typically within the hour) and will stop forwarding without "
                "further warning. Set AGENTMETRY_CHRONICLE_SERVICE_ACCOUNT for a "
                "credential that refreshes."
            )

    def _authorization(self) -> str | None:
        if self._credentials is not None:
            try:
                from google.auth.transport.requests import Request

                if not self._credentials.valid:
                    self._credentials.refresh(Request())
                return f"Bearer {self._credentials.token}"
            except Exception:
                logger.exception("Chronicle credential refresh failed")
                return None
        return f"Bearer {self._bearer}" if self._bearer else None

    async def emit(self, canonical: dict[str, Any]) -> None:
        authorization = self._authorization()
        if not authorization:
            return
        payload = canonical_to_udm_batch([canonical], customer_id=self._customer_id)
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json",
            "User-Agent": "Agentmetry/1.0",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, verify=self._verify) as client:
                response = await client.post(self._url, json=payload, headers=headers)
                response.raise_for_status()
        except Exception:
            # Same contract as every other network sink: the local trail is the
            # source of truth and a down SIEM must not raise into the hook path.
            logger.exception("Chronicle UDM POST failed -> %s", self._url)


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
        return {"file", "webhook", "elastic", "splunk", "chronicle"}
    return {part.strip() for part in text.split(",") if part.strip()}


def build_audit_sinks(
    *,
    modes: set[str],
    file_path: Path,
    webhook_url: str,
    webhook_timeout_seconds: float,
    webhook_format: str = "canonical",
    elastic_url: str,
    elastic_index: str,
    elastic_api_key: str,
    elastic_verify_tls: bool,
    splunk_hec_url: str,
    splunk_hec_token: str,
    splunk_index: str,
    splunk_sourcetype: str,
    splunk_verify_tls: bool,
    chronicle_endpoint: str = "",
    chronicle_customer_id: str = "",
    chronicle_service_account: str = "",
    chronicle_bearer_token: str = "",
    chronicle_verify_tls: bool = True,
) -> AuditSink | None:
    sinks: list[AuditSink] = []

    if "file" in modes:
        sinks.append(FileAuditSink(file_path))

    if "webhook" in modes and webhook_url.strip():
        sinks.append(
            WebhookAuditSink(
                webhook_url.strip(),
                timeout_seconds=webhook_timeout_seconds,
                format=webhook_format,
            )
        )

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

    if "chronicle" in modes and chronicle_endpoint.strip() and (
        chronicle_service_account.strip() or chronicle_bearer_token.strip()
    ):
        sinks.append(
            ChronicleUdmSink(
                chronicle_endpoint.strip(),
                chronicle_customer_id.strip(),
                service_account_file=chronicle_service_account.strip(),
                bearer_token=chronicle_bearer_token.strip(),
                timeout_seconds=webhook_timeout_seconds,
                verify_tls=chronicle_verify_tls,
            )
        )

    if not sinks:
        return None
    if len(sinks) == 1:
        return sinks[0]
    return MultiAuditSink(sinks)
