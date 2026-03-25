from __future__ import annotations

import json
import urllib.error
import urllib.request


def hf_chat_completion(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.0,
    endpoint: str = "https://router.huggingface.co/v1/chat/completions",
    provider: str = "",
    timeout_sec: int = 30,
) -> str:
    routed_model = model
    if provider and ":" not in model:
        routed_model = f"{model}:{provider}"

    payload = {
        "model": routed_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8")
        except Exception:
            err_body = str(exc)
        raise RuntimeError(f"HF_HTTP_{exc.code}: {err_body}") from exc
    except urllib.error.URLError as exc:
        raise ConnectionError(str(exc.reason)) from exc
