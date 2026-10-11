"""Ollama Embedding Adapter for local embeddings."""

import logging
from typing import Any, Dict
from urllib.parse import urljoin, urlparse

import httpx

from deeptutor.services.llm.openai_http_client import disable_ssl_verify_enabled

from .base import BaseEmbeddingAdapter, EmbeddingRequest, EmbeddingResponse
from .retry import retry_after_from_headers, run_with_bounded_retry

logger = logging.getLogger(__name__)


class OllamaEmbeddingAdapter(BaseEmbeddingAdapter):
    MODELS_INFO = {
        "all-minilm": 384,
        "all-mpnet-base-v2": 768,
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "snowflake-arctic-embed": 1024,
    }

    def _should_send_dimensions(self) -> bool:
        # Ollama models historically ignore the param, so default to NOT
        # sending unless the user explicitly opts in.
        return self.send_dimensions is True

    def _tags_url(self) -> str:
        # Probe `/api/tags` on the same host as the configured embed URL,
        # regardless of which embed path the user chose.
        parsed = urlparse(self.base_url)
        if parsed.scheme and parsed.netloc:
            return urljoin(f"{parsed.scheme}://{parsed.netloc}", "/api/tags")
        return urljoin(self.base_url, "/api/tags")

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if request.contents:
            raise ValueError(
                "Ollama embedding adapter does not support multimodal `contents` input."
            )

        payload = {
            "model": request.model or self.model,
            "input": request.texts,
        }

        dim_value = request.dimensions or self.dimensions
        if dim_value and self._should_send_dimensions():
            payload["dimensions"] = dim_value

        if request.truncate is not None:
            payload["truncate"] = request.truncate

        payload["keep_alive"] = "5m"

        url = self.base_url

        logger.debug(f"Sending embedding request to {url} with {len(request.texts)} texts")

        # Local servers juggle model loads under memory pressure: a fast
        # connect timeout surfaces a dead server quickly while a long read
        # timeout rides out cold model loading (aligned with
        # ``openai_compatible``).
        timeout = httpx.Timeout(
            connect=10.0,
            read=max(self.request_timeout, 60),
            write=10.0,
            pool=10.0,
        )

        async def _post_once() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=timeout, verify=not disable_ssl_verify_enabled()
            ) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={str(k): str(v) for k, v in self.extra_headers.items()},
                )

                if response.status_code == 404:
                    try:
                        health_check = await client.get(self._tags_url())
                        if health_check.status_code == 200:
                            available_models = [
                                m.get("name", "") for m in health_check.json().get("models", [])
                            ]
                            raise ValueError(
                                f"Model '{payload['model']}' not found in Ollama. "
                                f"Available models: {', '.join(available_models[:10])}. "
                                f"Download it with: ollama pull {payload['model']}"
                            )
                    except httpx.HTTPError:
                        pass

                    raise ValueError(
                        f"Model '{payload['model']}' not found. "
                        f"Download it with: ollama pull {payload['model']}"
                    )
                return response

        try:
            response = await run_with_bounded_retry(
                _post_once,
                provider="Ollama",
                status_of=lambda r: r.status_code,
                retry_after_of=lambda r: retry_after_from_headers(r.headers),
            )

            if response.status_code >= 400:
                response.raise_for_status()
            data = response.json()

        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}. "
                f"Make sure Ollama is running. Start it with: ollama serve"
            ) from e

        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"Request to Ollama timed out "
                f"(connect={timeout.connect:.0f}s, read={timeout.read:.0f}s). "
                f"The model might be too large or the server is overloaded."
            ) from e

        except httpx.HTTPError as e:
            logger.error(f"Ollama API error: {e}")
            raise

        embeddings = data["embeddings"]

        actual_dims = len(embeddings[0]) if embeddings else 0
        expected_dims = request.dimensions or self.dimensions

        if expected_dims and actual_dims != expected_dims:
            logger.warning(
                f"Dimension mismatch: expected {expected_dims}, got {actual_dims}. "
                f"Model '{payload['model']}' may not support custom dimensions."
            )

        logger.info(
            f"Successfully generated {len(embeddings)} embeddings "
            f"(model: {data.get('model', self.model)}, dimensions: {actual_dims})"
        )

        return EmbeddingResponse(
            embeddings=embeddings,
            model=data.get("model", self.model),
            dimensions=actual_dims,
            usage={
                "prompt_eval_count": data.get("prompt_eval_count", 0),
                "total_duration": data.get("total_duration", 0),
            },
        )

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "dimensions": self.MODELS_INFO.get(self.model, self.dimensions),
            "local": True,
            "supports_variable_dimensions": False,
            "multimodal": False,
            "provider": "ollama",
        }
