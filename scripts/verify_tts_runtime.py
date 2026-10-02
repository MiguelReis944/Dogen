"""Smoke-test the packaged Coqui import path without downloading a voice model."""

import os
import sys

from scripts.preflight import check_tts


TTS_MODEL = "tts_models/en/ljspeech/tacotron2-DDC"


def redirect_numba_cache_for_smoke():
    """Keep Numba's frozen-app cache inside the disposable build smoke folder."""
    cache_dir = os.environ.get("DOGEN_TTS_SMOKE_CACHE")
    if not cache_dir or not getattr(sys, "frozen", False):
        return

    os.environ["NUMBA_CACHE_LOCATOR_CLASSES"] = "UserWideCacheLocator"
    from numba.core import caching, config

    config.CACHE_LOCATOR_CLASSES = "UserWideCacheLocator"

    class SmokeAppDirs:
        def __init__(self, appname=None, appauthor=None, **kwargs):
            self.user_cache_dir = cache_dir

    caching.AppDirs = SmokeAppDirs


def run_smoke_check():
    """Return a process status after exercising the setup wizard's TTS check."""
    try:
        redirect_numba_cache_for_smoke()
        # A missing cached model is expected in a clean setup. The important part
        # is that Coqui and its configuration dependencies import successfully.
        check_tts(TTS_MODEL)
    except Exception as exc:
        print(
            f"Voice runtime smoke test failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    if not getattr(sys, "frozen", False):
        raise SystemExit("This smoke test must run from the frozen app bundle.")
    raise SystemExit(run_smoke_check())
