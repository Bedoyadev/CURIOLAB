"""Calls to the Claude API that must come back as data of a known shape.

Uses the API's structured outputs (output_config.format with a JSON schema): the answer is
guaranteed to parse and to carry every field, and an id field declared as an enum can only hold a
registered id. The schema is not the last word, though: what comes back is still validated by the
caller (storyboard.validate) before anything is drawn.
"""
import asyncio
import json

import anthropic

from animation.shared.settings import PRICES_PER_MTOK, anthropic_key

MAX_TOKENS = 16000


class LLMError(Exception):
    pass


def obj(properties: dict) -> dict:
    """An object schema as structured outputs wants it: every field required, nothing extra."""
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


def enum(values) -> dict:
    return {"type": "string", "enum": list(values)}


STR, NUM, INT, BOOL = {"type": "string"}, {"type": "number"}, {"type": "integer"}, {"type": "boolean"}


def cost_of(model: str, usage) -> float:
    inp, out = PRICES_PER_MTOK.get(model, (4.0, 20.0))
    return (usage.input_tokens * inp + usage.output_tokens * out) / 1_000_000


async def ask(model: str, system: str, user: str, schema: dict, ledger, detail: str, effort: str = "medium") -> dict:
    """One structured answer. The budget is checked before the call and the cost recorded after."""
    ledger.check()
    client = anthropic.Anthropic(api_key=anthropic_key())
    try:
        response = await asyncio.to_thread(
            client.messages.create, model=model, max_tokens=MAX_TOKENS, system=system,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}])
    except anthropic.APIStatusError as e:
        raise LLMError(f"Claude rechazó la petición ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError(f"no se pudo conectar con Claude: {e}") from e
    ledger.add("claude", cost_of(model, response.usage), detail)
    if response.stop_reason == "refusal":
        raise LLMError("Claude declinó responder a esta petición")
    if response.stop_reason == "max_tokens":
        raise LLMError("la respuesta de Claude quedó cortada por el límite de tokens")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise LLMError("la respuesta de Claude no trae texto")
    try:
        return json.loads(text)
    except ValueError as e:
        raise LLMError(f"la respuesta de Claude no es JSON válido: {e}") from e
