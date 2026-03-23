"""
L2Bot — Lineage 2 MITM Proxy Bot
Entry point: starts Login + Game proxies and the UI.

Usage:
    python main.py [--no-ui] [--config path/to/settings.ini]

Flow:
    1. Read settings.ini
    2. Patch L2.ini to redirect client to localhost (optional if already done)
    3. Start Login Proxy on localhost:2106
    4. Start Game Proxy on localhost:7777
    5. Start UI (customtkinter) in main thread
    6. asyncio event loop runs in background thread

The UI communicates with the asyncio loop via asyncio.run_coroutine_threadsafe().
"""
import argparse
import asyncio
import configparser
import logging
import os
import sys
import threading
from pathlib import Path

# ---- configure logging early ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("l2bot.main")

from core.proxy.login_proxy import LoginProxyServer
from core.proxy.game_proxy import GameProxyServer
from core.proxy.session import LoginSession, GameSession
from core.protocol import registry
from engine.bot import BotEngine


def load_config(path: str = "config/settings.ini") -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    return cfg


def get_server_cfg(cfg: configparser.ConfigParser) -> configparser.SectionProxy:
    """Return the active server section, e.g. [server.bartz]."""
    active = cfg.get("active", "server", fallback="bartz")
    section = f"server.{active}"
    if not cfg.has_section(section):
        raise RuntimeError(f"No section [{section}] in settings.ini")
    log.info("Active server profile: [%s]", section)
    return cfg[section]


def patch_l2_ini(l2_exe_path: str, login_host: str = "127.0.0.1") -> bool:
    """
    Patch l2.ini in the same folder as L2.exe to point LoginHost to our proxy.
    Returns True if patched, False if file not found.
    """
    system_dir = Path(l2_exe_path).parent
    l2_ini = system_dir / "l2.ini"
    if not l2_ini.exists():
        log.warning("l2.ini not found at %s — cannot auto-patch", l2_ini)
        return False

    content = l2_ini.read_text(encoding="utf-8", errors="replace")
    import re
    patched = re.sub(
        r"((?:LoginHost|ServerAddr)\s*=\s*)[\w\.\-]+",
        rf"\g<1>{login_host}",
        content,
    )
    if patched != content:
        l2_ini.write_text(patched, encoding="utf-8")
        log.info("Patched l2.ini: LoginHost → %s", login_host)
    else:
        log.info("l2.ini already points to %s (no patch needed)", login_host)
    return True


class BotCore:
    """Holds all running components and exposes the bot API."""

    def __init__(self, cfg: configparser.ConfigParser):
        self.cfg = cfg
        self.loop: asyncio.AbstractEventLoop | None = None
        self.login_proxy: LoginProxyServer | None = None
        self.game_proxy: GameProxyServer | None = None
        self.login_session = LoginSession()
        self.game_session = GameSession()
        self.bot_engine: BotEngine | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start asyncio event loop in a background thread."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="l2bot-loop")
        self._thread.start()

    def _run_loop(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._async_main())
        except (RuntimeError, asyncio.CancelledError):
            pass

    async def _async_main(self) -> None:
        cfg = self.cfg
        srv = get_server_cfg(cfg)

        # Chronicle
        chronicle = srv.get("chronicle", "interlude")
        registry.set_chronicle(chronicle)
        log.info("Chronicle: %s", chronicle)

        # Update log level
        log_level = cfg.get("bot", "log_level", fallback="INFO")
        logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))

        # Patch l2.ini
        l2_path = srv.get("l2_path", "")
        if l2_path and os.path.exists(l2_path):
            patch_l2_ini(l2_path)
        else:
            log.info("l2_path not configured or not found — skipping l2.ini patch")

        # Start Login Proxy
        real_login_host = srv.get("login_host", "127.0.0.1")
        real_login_port = srv.getint("login_port", fallback=2106)
        listen_login_port = cfg.getint("proxy", "listen_login_port", fallback=2106)
        listen_game_port = cfg.getint("proxy", "listen_game_port", fallback=7777)

        # Wire session so LoginProxy can tell GameProxy the real server address
        self.login_session.listen_game_port = listen_game_port

        # Start Game Proxy first (needs to be listening before client connects)
        real_game_host = srv.get("game_host", "127.0.0.1")
        real_game_port = srv.getint("game_port", fallback=7777)

        self.game_proxy = GameProxyServer(
            real_host=real_game_host,
            real_port=real_game_port,
            listen_port=listen_game_port,
            session=self.game_session,
        )
        await self.game_proxy.start()

        # When LoginProxy discovers the real game server from ServerList packet,
        # update GameProxy's target host/port
        def _on_game_server_discovered(host: str, port: int) -> None:
            log.info("Game server discovered from ServerList: %s:%d", host, port)
            self.game_proxy.real_host = host
            self.game_proxy.real_port = port

        self.login_session.on_game_server_discovered = _on_game_server_discovered

        self.login_proxy = LoginProxyServer(
            real_host=real_login_host,
            real_port=real_login_port,
            listen_port=listen_login_port,
            session=self.login_session,
        )
        await self.login_proxy.start()

        # Start bot engine
        self.bot_engine = BotEngine(self.game_proxy)
        self.bot_engine.start()

        log.info("L2Bot ready. Start your L2 client and log in.")
        log.info("Login proxy: localhost:%d → %s:%d",
                 listen_login_port, real_login_host, real_login_port)
        log.info("Game proxy:  localhost:%d → %s:%d",
                 listen_game_port, real_game_host, real_game_port)

        # Keep running forever (cancelled cleanly on stop())
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass

    def stop(self) -> None:
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._async_stop(), self.loop)

    async def _async_stop(self) -> None:
        if self.login_proxy:
            await self.login_proxy.stop()
        if self.game_proxy:
            await self.game_proxy.stop()
        self.loop.stop()

    def inject_to_server(self, opcode: int, payload: bytes) -> None:
        """Thread-safe: inject a packet toward the game server."""
        if self.loop and self.game_proxy:
            self.loop.call_soon_threadsafe(
                self.game_proxy.inject_to_server, opcode, payload
            )

    def start_auto_combat(self, combat_range: float = 2000.0) -> None:
        """Thread-safe: start auto-combat loop in the bot engine."""
        if self.loop and self.bot_engine:
            self.loop.call_soon_threadsafe(
                self.bot_engine.start_auto_combat, combat_range)

    def stop_auto_combat(self) -> None:
        """Thread-safe: stop auto-combat loop."""
        if self.loop and self.bot_engine:
            self.loop.call_soon_threadsafe(self.bot_engine.stop_auto_combat)

    def sit_stand(self) -> None:
        """Thread-safe: toggle sit/stand."""
        if self.loop and self.bot_engine:
            self.loop.call_soon_threadsafe(self.bot_engine.sit_stand)


def main() -> None:
    parser = argparse.ArgumentParser(description="L2Bot — Lineage 2 MITM Proxy Bot")
    parser.add_argument("--no-ui", action="store_true", help="Run without GUI (CLI mode)")
    parser.add_argument("--config", default="config/settings.ini", help="Path to settings.ini")
    args = parser.parse_args()

    cfg = load_config(args.config)
    bot = BotCore(cfg)
    bot.start()

    if args.no_ui:
        log.info("Running in CLI mode. Press Ctrl+C to stop.")
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Shutting down...")
            bot.stop()
        return

    # Start GUI
    try:
        from ui.app import L2BotApp
        app = L2BotApp(bot)
        app.mainloop()
    except ImportError as e:
        log.warning("GUI not available (%s). Running in CLI mode.", e)
        log.info("Install UI deps: pip install customtkinter")
        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
