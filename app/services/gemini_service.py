"""Google Gemini integration.

- Model name and API key are always read from settings (env vars) - never
  hard-coded, per project requirements.
- Structured output is requested via response_schema=DocumentResult so the
  SDK enforces JSON shape server-side; we additionally re-validate with
  Pydantic before trusting the result.
- Retries use exponential backoff and only apply to transient failures
  (timeouts, 5xx, rate limits). Malformed JSON / auth errors are not retried
  indefinitely.
"""

from __future__ import annotations

import logging

from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config.settings import get_settings
from app.schemas.extraction import DocumentResult
from app.services import prompts

logger = logging.getLogger(__name__)


class GeminiServiceError(Exception):
    """Raised for permanent (non-retryable) Gemini failures."""


class GeminiTransientError(Exception):
    """Raised for retryable Gemini failures (timeouts, rate limits, 5xx)."""


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, GeminiTransientError):
        return True
    if isinstance(exc, ServerError):
        return True
    if isinstance(exc, ClientError):
        # 429 = rate limited, still worth retrying with backoff.
        return getattr(exc, "code", None) == 429
    return False


class GeminiService:
    def __init__(self) -> None:
        self._settings = get_settings()
        if not self._settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY is not set - Gemini calls will fail until configured.")
        self._client = genai.Client(api_key=self._settings.gemini_api_key)

    def _retrying(self):
        return retry(
            reraise=True,
            stop=stop_after_attempt(self._settings.gemini_max_retries),
            wait=wait_exponential(multiplier=1.5, min=2, max=30),
            retry=retry_if_exception(_is_transient),
        )

    async def _generate(self, contents: list) -> str:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DocumentResult,
            temperature=0.0,
            # Explicit, generous ceiling (not the SDK/model implicit
            # default): a dense, content-heavy scan - e.g. a bilingual
            # official notice with the same text repeated in two languages
            # on one page - can genuinely need a large JSON response. Left
            # unset, a real case truncated mid-generation and (because
            # response_schema uses constrained decoding) still came back as
            # syntactically *valid* JSON with only 3 blocks - no error, no
            # warning, just silently missing almost the whole document.
            # finish_reason is checked below specifically to catch this
            # class of failure even if max_output_tokens still isn't enough.
            max_output_tokens=self._settings.gemini_max_output_tokens,
        )

        @self._retrying()
        async def _call() -> str:
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._settings.gemini_model,
                    contents=contents,
                    config=config,
                )
            except (TimeoutError, ConnectionError) as exc:
                raise GeminiTransientError(str(exc)) from exc
            except APIError as exc:
                if getattr(exc, "code", None) in (429, 500, 502, 503, 504):
                    raise GeminiTransientError(str(exc)) from exc
                raise GeminiServiceError(f"Gemini API хатоси: {exc}") from exc

            if not response or not response.text:
                raise GeminiTransientError("Empty response from Gemini")

            self._check_finish_reason(response)
            return response.text

        return await _call()

    @staticmethod
    def _check_finish_reason(response: types.GenerateContentResponse) -> None:
        """Rejects a response that didn't finish cleanly, even if the
        (possibly truncated) text still happened to parse as valid JSON -
        see the max_output_tokens comment in _generate for the real
        incident this guards against.
        """
        candidates = response.candidates or []
        if not candidates:
            return
        finish_reason = candidates[0].finish_reason
        if finish_reason is None or finish_reason == types.FinishReason.STOP:
            return
        if finish_reason == types.FinishReason.MAX_TOKENS:
            raise GeminiServiceError(
                "Ҳужжат мазмуни жуда катта - Gemini жавоби чекланган узунликда кесилди "
                "ва натижа тўлиқ бўлмайди. Ҳужжатни бўлакларга бўлиб (масалан, ҳар "
                "саҳифани алоҳида расм қилиб) қайта юборинг."
            )
        raise GeminiServiceError(f"Gemini генерацияси кутилмаганда тўхтади ({finish_reason}).")

    def _validate(self, raw_json: str) -> DocumentResult:
        try:
            return DocumentResult.model_validate_json(raw_json)
        except ValidationError as exc:
            logger.error("Gemini returned JSON that failed schema validation: %s", exc)
            raise GeminiServiceError("Gemini кутилмаган жавоб формати қайтарди.") from exc

    async def extract_from_text(self, page_texts: dict[int, str], filename_hint: str) -> DocumentResult:
        prompt = prompts.build_text_structuring_prompt(page_texts, filename_hint)
        raw_json = await self._generate([prompt])
        return self._validate(raw_json)

    async def extract_from_images(
        self,
        images: list[bytes],
        page_numbers: list[int],
        is_handwritten_hint: bool = False,
        image_mime_type: str = "image/png",
    ) -> DocumentResult:
        prompt = prompts.build_vision_extraction_prompt(page_numbers, is_handwritten_hint)
        contents: list = [prompt]
        for image_bytes in images:
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime_type))
        raw_json = await self._generate(contents)
        return self._validate(raw_json)


_service: GeminiService | None = None


def get_gemini_service() -> GeminiService:
    global _service
    if _service is None:
        _service = GeminiService()
    return _service
