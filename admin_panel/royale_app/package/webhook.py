"""
The one door Grand Line Royale knocks on.

Royale runs as a plain process on the same host; this bot runs in a container. So the port is
published on the host's loopback only (`127.0.0.1:15262` in `docker-compose.override.yml`) and
the server inside the container listens on every interface, which is what lets the published
port reach it. Nothing is routed through nginx and nothing is reachable from the internet.

The answers matter as much as the scoring, because they tell Royale whether to forget a report
or keep it. Royale drops a report only on 2xx and 400 — everything else it keeps and retries —
so the rule here is: **400 is only ever for a body no retry could fix.** A missing route, a
server not in the allowed list, a bridge switched off: all of those are fixed by a deploy or by
a line in the admin panel, so they must not be 400.
"""

import logging
import secrets
from typing import TYPE_CHECKING

from aiohttp import web

from ..models import RoyaleSettings
from ..scoring import ReportError, ingest, validate

if TYPE_CHECKING:
    from ballsdex.core.bot import BallsDexBot

log = logging.getLogger("ballsdex.royale_bridge")

WEBHOOK_PORT = 15262
WEBHOOK_PATH = "/webhook/kots"

_runner: "web.AppRunner | None" = None


def _bearer(request: web.Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


async def handle_report(request: web.Request) -> web.Response:
    """One end-of-match report from Royale."""
    # read afresh every time, so switching the bridge off or rolling the secret takes effect
    # without restarting the bot
    config = await RoyaleSettings.aload()

    if not config.shared_secret:
        log.warning("royale bridge: a report arrived but the shared secret has been cleared")
        return web.json_response({"error": "the bridge has no secret configured"}, status=503)

    # compared as bytes, so a secret someone pasted with an accent in it is a plain mismatch
    # rather than a TypeError that would answer 500 where 401 is the truth
    provided = _bearer(request)
    if not provided or not secrets.compare_digest(
        provided.encode("utf-8", "replace"), config.shared_secret.encode("utf-8", "replace")
    ):
        log.warning("royale bridge: a report arrived with a wrong or missing secret")
        return web.json_response({"error": "wrong or missing secret"}, status=401)

    if not config.enabled:
        return web.json_response({"error": "the bridge is switched off"}, status=503)

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
        log.warning(
            "royale bridge: refused a report from server %s, which is not in the allowed list", guild_id
        )
        return web.json_response({"error": f"server {guild_id} is not allowed"}, status=403)

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


async def start_webhook_server(bot: "BallsDexBot") -> "web.AppRunner | None":
    """
    Start listening, unless no secret is set.

    With the secret empty there is nothing to check a report against, so the socket is never
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
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    # every interface inside the container: the host only publishes this on its loopback
    site = web.TCPSite(runner, host="0.0.0.0", port=WEBHOOK_PORT)
    await site.start()
    _runner = runner
    log.info("Royale webhook server started on port %s, path %s", WEBHOOK_PORT, WEBHOOK_PATH)
    return runner


async def stop_webhook_server() -> None:
    """Give the socket back, so reloading the package does not leave it held."""
    global _runner

    if _runner is None:
        return
    await _runner.cleanup()
    _runner = None
    log.info("Royale webhook server stopped")
