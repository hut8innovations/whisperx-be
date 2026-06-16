"""
RunPod serverless client — the only thing that talks to the model.

The endpoint (Slice 0, kodxana/whisperx-worker fork) is async:
  submit -> POST /v2/{id}/run            -> {"id": <job>, "status": "IN_QUEUE"}
  poll   -> GET  /v2/{id}/status/{job}   -> until status == COMPLETED / FAILED

Audio is passed as a URL (the worker fetches it); the HF token lives on the
endpoint, so the app never sends it. `shape()` collapses the worker's rich
output (segment- AND word-level speaker labels) down to the product contract.
"""

import time

import httpx

from .config import settings

_http = httpx.Client(timeout=30.0)
_BASE = "https://api.runpod.ai/v2"


class RunPodError(Exception):
    """Job failed, or the endpoint returned something unexpected."""


class RunPodTimeout(RunPodError):
    """Job did not reach COMPLETED within the poll budget."""


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type": "application/json",
    }


def transcribe(
    audio_url: str,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> dict:
    """Submit a job and block until it completes. Returns the worker `output` dict."""
    payload: dict = {
        "input": {
            "audio_file": audio_url,
            "align_output": True,
            "diarization": True,
        }
    }
    if min_speakers is not None:
        payload["input"]["min_speakers"] = min_speakers
    if max_speakers is not None:
        payload["input"]["max_speakers"] = max_speakers

    submit = _http.post(
        f"{_BASE}/{settings.runpod_endpoint_id}/run",
        headers=_headers(),
        json=payload,
    )
    submit.raise_for_status()
    job_id = submit.json().get("id")
    if not job_id:
        raise RunPodError(f"No job id in submit response: {submit.text}")

    deadline = time.time() + settings.runpod_poll_timeout_s
    while time.time() < deadline:
        poll = _http.get(
            f"{_BASE}/{settings.runpod_endpoint_id}/status/{job_id}",
            headers=_headers(),
        )
        poll.raise_for_status()
        data = poll.json()
        status = data.get("status")
        if status == "COMPLETED":
            return data.get("output") or {}
        if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
            raise RunPodError(f"Job {job_id} {status}: {data.get('error')}")
        time.sleep(settings.runpod_poll_interval_s)

    raise RunPodTimeout(
        f"Job {job_id} not COMPLETED within {settings.runpod_poll_timeout_s}s"
    )


def shape(output: dict) -> dict:
    """Worker output -> product contract.

    Drops word-level detail from the response (kept inside the worker only),
    trims segment text, and synthesises the full transcript the worker omits.
    `audio_seconds` is the last segment's end time — used for metering.
    """
    raw = output.get("segments") or []
    segments = [
        {
            "speaker": s.get("speaker"),
            "start": s.get("start"),
            "end": s.get("end"),
            "text": (s.get("text") or "").strip(),
        }
        for s in raw
    ]
    full_transcript = " ".join(seg["text"] for seg in segments if seg["text"])
    audio_seconds = max((s.get("end") or 0) for s in raw) if raw else 0.0
    return {
        "segments": segments,
        "full_transcript": full_transcript,
        "detected_language": output.get("detected_language"),
        "audio_seconds": float(audio_seconds),
    }
