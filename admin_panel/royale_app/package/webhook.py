"""
The two doors Grand Line Royale knocks on.

`POST /webhook/kots` takes an end-of-match report and turns it into crew war points.
`POST /api/crews` answers who flies which flag, which Royale needs for one rule: you may not
strike someone of your own crew.

Royale runs as a plain process on the same host; this bot runs in a container. So the port is
published on the host's loopback only (`127.0.0.1:15262` in `docker-compose.override.yml`) and
the server inside the container listens on every interface, which is what lets the published
port reach it. Nothing is routed through nginx and nothing is reachable from the internet.

The answers matter as much as the work, because they tell Royale whether to forget a report or
keep it. Royale drops a report only on 2xx and 400 — everything else it keeps and retries — so
the rule here is: **400 is only ever for a body no retry could fix.** A missing route, a server
not in the allowed list, a bridge switched off: all of those are fixed by a deploy or by a line
in the admin panel, so none of them must be a 400.
"""

import logging
import secrets
from typing import TYPE_CHECKING

from aiohttp import web

from ..membership import LookupError_, crews_of, validate_lookup
from ..models import RoyaleSettings
from ..scoring import ReportError, ingest, validate

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.royale_bridge")

WEBHOOK_PORT = 15262
WEBHOOK_PATH = "/webhook/kots"
CREWS_PATH = "/api/crews"

_runner: "web.AppRunner | None" = None


def _bearer(request: web.Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


async def _admitted(request: web.Request) -> "tuple[RoyaleSettings | None, web.Response | None]":
    """
    The settings when the caller may go on, or the answer to send it back.

    Read afresh on every request, so switching the bridge off or rolling the secret takes effect
    without restarting the bot. `enabled` gates both doors on purpose: the bridge is one thing,
    and a war mode must not keep running on half of it.
    """
    config = await RoyaleSettings.aload()

    if not config.shared_secret:
        log.warning("royale bridge: a request arrived but the shared secret has been cleared")
        return None, web.json_response({"error": "the bridge has no secret configured"}, status=503)

    # compared as bytes, so a secret someone pasted with an accent in it is a plain mismatch
    # rather than a TypeError that would answer 500 where 401 is the truth
    provided = _bearer(request)
    if not provided or not secrets.compare_digest(
        provided.encode("utf-8", "replace"), config.shared_secret.encode("utf-8", "replace")
    ):
        log.warning("royale bridge: a request arrived with a wrong or missing secret")
        return None, web.json_response({"error": "wrong or missing secret"}, status=401)

    if not config.enabled:
        return None, web.json_response({"error": "the bridge is switched off"}, status=503)

    return config, None


def _refuse_server(guild_id) -> web.Response:
    log.warning("royale bridge: refused a request from server %s, which is not in the allowed list", guild_id)
    return web.json_response({"error": f"server {guild_id} is not allowed"}, status=403)


async def handle_report(request: web.Request) -> web.Response:
    """One end-of-match report from Royale."""
    config, refusal = await _admitted(request)
    if refusal is not None:
        return refusal

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "the body is not valid JSON"}, status=400)

    try:
        body = validate(body)
    except ReportError as error:
        log.warning("royale bridge: refused a report for good — %s", error)
        return web.json_response({"error": str(error)}, status=400)

    guild_id = body.get("guild_id")
    if not config.allows(guild_id):
        return _refuse_server(guild_id)

    try:
        row, created = await ingest(body)
    except Exception:
        # kept and retried by Royale. If the match row was already written, the retry answers
        # "duplicate" and nothing is paid twice.
        log.exception("royale bridge: could not score the report %s", body.get("match_id"))
        return web.json_response({"error": "the report could not be scored"}, status=500)

    if not created:
        return web.json_response({"status": "duplicate"})
    return web.json_response({"status": "scored", "players_scored": row.players_known})


async def handle_crews(request: web.Request) -> web.Response:
    """
    Who flies which flag, for the players of one lobby.

    Asked once when a match starts, and held by Royale for that match only. A crew this bot has
    no membership row for comes back as `null`, which Royale reads as a faction of one.
    """
    config, refusal = await _admitted(request)
    if refusal is not None:
        return refusal

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "the body is not valid JSON"}, status=400)

    guild_id = body.get("guild_id") if isinstance(body, dict) else None
    if not config.allows(guild_id):
        return _refuse_server(guild_id)

    try:
        discord_ids = validate_lookup(body)
    except LookupError_ as error:
        log.warning("royale bridge: refused a crew lookup for good — %s", error)
        return web.json_response({"error": str(error)}, status=400)

    try:
        members = await crews_of(discord_ids)
    except Exception:
        # Royale is told to refuse to start a crew war rather than fall back to a free-for-all,
        # so this must be a code it retries, never a 400.
        log.exception("royale bridge: could not look up the crews of %s players", len(discord_ids))
        return web.json_response({"error": "the crews could not be read"}, status=500)

    return web.json_response({"members": members})


async def start_webhook_server(bot: "BallsDexBot") -> "web.AppRunner | None":
    """
    Start listening, unless no secret is set.

    With the secret empty there is nothing to check a request against, so the socket is never
    opened at all — the same way the vote webhook stays down without its own secret. Royale then
    gets a refused connection, which it keeps and retries, so no report is lost by the bridge
    being off.
    """
    global _runner

    config = await RoyaleSettings.aload()
    if not config.shared_secret:
        log.info("No Royale shared secret configured, the Royale webhook server stays disabled.")
        return None

    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_report)
    app.router.add_post(CREWS_PATH, handle_crews)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    # every interface inside the container: the host only publishes this on its loopback
    site = web.TCPSite(runner, host="0.0.0.0", port=WEBHOOK_PORT)
    await site.start()
    _runner = runner
    log.info("Royale webhook server started on port %s, paths %s and %s", WEBHOOK_PORT, WEBHOOK_PATH, CREWS_PATH)
    return runner


async def stop_webhook_server() -> None:
    """Give the socket back, so reloading the package does not leave it held."""
    global _runner

    if _runner is None:
        return
    await _runner.cleanup()
    _runner = None
    log.info("Royale webhook server stopped")
