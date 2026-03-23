"""
Bot Engine — hooks into GameProxy, routes packets to World, exposes bot actions.

Usage:
    from engine.bot import BotEngine
    bot_engine = BotEngine(game_proxy)
    bot_engine.start()          # hooks into proxy
    bot_engine.stop()
"""
import asyncio
import logging
import time
from typing import Optional

from core.proxy.game_proxy import GameProxyServer
from core.packets.server import (
    UserInfo, NpcInfo, DeleteObject, StatusUpdate, MoveToPoint, Die, TargetSelected,
    SpawnItem, Attack,
)
from core.packets import client as cs
from core.protocol.opcode_detector import OpcodeDetector
from engine.world import World, Npc, GroundItem

log = logging.getLogger(__name__)


class BotEngine:
    def __init__(self, game_proxy: GameProxyServer):
        self.game_proxy = game_proxy
        self.world = World()
        self._running = False

        # Opcode detector — resolves per-session XOR scrambling
        self._detector = OpcodeDetector()
        self._detector.on_ready = self._on_opcodes_detected

        # Packet opcode → handler method (rebuilt after opcode detection)
        self._handlers: dict[int, object] = {}

        # Auto-combat state
        self._auto_combat = False
        self._combat_range = 2000.0
        self._auto_task: Optional[asyncio.Task] = None

        # Auto-loot
        self._auto_loot = True
        self._loot_range = 800.0

        # Debug: hex dump first N NpcInfo packets to verify parser alignment
        self._npc_debug_count = 0
        self._npc_debug_max = 3

        # Debug: hex dump unhandled packets (first 2 of each opcode)
        self._unhandled_hex_seen: dict[int, int] = {}
        self._unhandled_hex_max = 2

        # Track Die events for post-kill packet analysis
        self._last_die_time: float = 0

        # Buffer NpcInfo-sized packets that arrive before opcode detection fires.
        # Replayed once handlers are ready so we don't lose the initial mob population.
        self._pre_detect_npc_buf: list[tuple[int, bytes]] = []

    def start(self) -> None:
        """Hook into GameProxy to receive server packets."""
        self.game_proxy.on_server_packet = self._dispatch
        self.game_proxy.on_new_session = self._on_new_session
        self._detector.reset()
        log.info("[BotEngine] Started — listening for game packets")

    def _on_new_session(self) -> None:
        """Called when game client reconnects — reset opcode detector."""
        self._handlers.clear()
        self._detector.reset()
        self.world = World()
        self._pre_detect_npc_buf.clear()
        self._npc_debug_count = 0
        self._unhandled_hex_seen.clear()
        self._last_die_time = 0
        log.info("[BotEngine] New game session — opcode detector reset")

    def stop(self) -> None:
        self._running = False
        self.game_proxy.on_server_packet = None
        self.game_proxy.on_new_session = None
        log.info("[BotEngine] Stopped")

    # ------------------------------------------------------------------ #
    # Opcode detection
    # ------------------------------------------------------------------ #

    def _on_opcodes_detected(self, opcodes: dict[str, int]) -> None:
        """Called by OpcodeDetector once XOR key is determined."""
        self._handlers = {
            opcodes["UserInfo"]:          self._on_user_info,
            opcodes["NpcInfo"]:           self._on_npc_info,
            opcodes["DeleteObject"]:      self._on_delete_object,
            opcodes["StatusUpdate"]:      self._on_status_update,
            opcodes["MoveToPoint"]:       self._on_move,
            opcodes["Die"]:               self._on_die,
            opcodes["TargetSelected"]:    self._on_target_selected,
            opcodes["SpawnItem"]:         self._on_spawn_item,
            opcodes["StatusUpdate2"]:     self._on_status_update,
            opcodes["Attack"]:            self._on_attack,
            opcodes["Die2"]:              self._on_die,
        }
        log.info("[BotEngine] Opcodes updated — handlers ready (XOR key=0x%02X)",
                 self._detector.xor_key)

        # Replay NpcInfo packets that arrived before detection fired
        npc_opcode = opcodes["NpcInfo"]
        replayed = 0
        for op, pld in self._pre_detect_npc_buf:
            if op == npc_opcode:
                try:
                    self._on_npc_info(pld)
                    replayed += 1
                except Exception:
                    pass
        self._pre_detect_npc_buf.clear()
        log.debug("[BotEngine] Replayed %d buffered NpcInfo packets", replayed)

    # ------------------------------------------------------------------ #
    # Packet dispatch
    # ------------------------------------------------------------------ #

    async def _dispatch(self, opcode: int, payload: bytes) -> None:
        # Always feed detector (no-op once ready)
        self._detector.feed(opcode, len(payload))

        # Buffer potential NpcInfo packets arriving before detection fires
        if not self._handlers and len(payload) == 187:
            self._pre_detect_npc_buf.append((opcode, payload))

        handler = self._handlers.get(opcode)
        if handler:
            try:
                handler(payload)
            except Exception as exc:
                log.error("[BotEngine] Handler 0x%02X error: %s", opcode, exc)
        else:
            # Hex dump unhandled packets within 3s of mob death to find SpawnItem
            since_die = time.monotonic() - self._last_die_time if self._last_die_time else 999
            if since_die < 3.0 and len(payload) >= 16:
                log.info("[POST-KILL] 0x%02X (%dB) hex: %s",
                         opcode, len(payload), payload[:32].hex(' '))
            # Also hex dump first 2 of each unknown opcode (>= 20 bytes)
            seen = self._unhandled_hex_seen.get(opcode, 0)
            if seen < self._unhandled_hex_max and len(payload) >= 20:
                self._unhandled_hex_seen[opcode] = seen + 1
                log.info("[UNKNOWN] 0x%02X (%dB) hex: %s",
                         opcode, len(payload), payload[:32].hex(' '))
            else:
                log.debug("[BotEngine] Unhandled 0x%02X (%d bytes)", opcode, len(payload))

    # ------------------------------------------------------------------ #
    # Packet handlers
    # ------------------------------------------------------------------ #

    def _on_user_info(self, payload: bytes) -> None:
        pkt = UserInfo.parse(payload)
        self.world.on_user_info(pkt)
        me = self.world.me
        log.info("[World] Me: '%s' objId=0x%X lvl=%d  HP:%d/%d  MP:%d/%d  pos=(%d,%d,%d)",
                 me.name, me.object_id, pkt.level, me.cur_hp, me.max_hp,
                 me.cur_mp, me.max_mp, me.x, me.y, me.z)

    def _on_npc_info(self, payload: bytes) -> None:
        # Hex dump first few NpcInfo packets for debugging parser alignment
        if self._npc_debug_count < self._npc_debug_max:
            self._npc_debug_count += 1
            hex_str = payload[:60].hex(' ')
            log.info("[NpcInfo HEX] #%d (%dB) first 60 bytes: %s",
                     self._npc_debug_count, len(payload), hex_str)
            # Also show bytes around name offset (121+)
            if len(payload) > 121:
                log.info("[NpcInfo HEX] #%d bytes[116:140]: %s",
                         self._npc_debug_count, payload[116:140].hex(' '))
        pkt = NpcInfo.parse(payload)
        self.world.on_npc_info(pkt)
        atk = "ATK" if pkt.is_attackable else "npc"
        dead = " DEAD" if pkt.is_dead else ""
        log.debug("[World] %s npcId=%d '%s' '%s' pos=(%d,%d,%d)%s [%dB]",
                 atk, pkt.npc_id, pkt.name, pkt.title, pkt.x, pkt.y, pkt.z, dead,
                 len(payload))

    def _on_delete_object(self, payload: bytes) -> None:
        pkt = DeleteObject.parse(payload)
        self.world.on_delete_object(pkt)

    def _on_status_update(self, payload: bytes) -> None:
        pkt = StatusUpdate.parse(payload)
        # Debug: log raw attrs for first few NPC StatusUpdates
        if pkt.object_id != self.world.me.object_id and pkt.attrs:
            log.info("[StatusUpdate] objId=0x%X attrs=%s [%dB hex: %s]",
                     pkt.object_id, pkt.attrs, len(payload), payload[:20].hex(' '))
        self.world.on_status_update(pkt)
        if pkt.object_id == self.world.me.object_id:
            me = self.world.me
            log.debug("[World] My status → HP:%d/%d MP:%d/%d",
                      me.cur_hp, me.max_hp, me.cur_mp, me.max_mp)
        elif pkt.object_id in self.world.npcs:
            npc = self.world.npcs[pkt.object_id]
            if npc.max_hp > 0:
                log.debug("[World] NPC status objId=0x%X npcId=%d → HP:%d/%d (%.0f%%)",
                          npc.object_id, npc.npc_id, npc.cur_hp, npc.max_hp, npc.hp_pct)

    def _on_move(self, payload: bytes) -> None:
        pkt = MoveToPoint.parse(payload)
        if pkt.object_id == self.world.me.object_id:
            log.debug("[World] MoveToPoint me → orig=(%d,%d) dest=(%d,%d)",
                      pkt.orig_x, pkt.orig_y, pkt.dest_x, pkt.dest_y)
        self.world.on_move(pkt)

    def _on_die(self, payload: bytes) -> None:
        pkt = Die.parse(payload)
        self.world.on_die(pkt)
        self._last_die_time = time.monotonic()
        if pkt.object_id == self.world.me.object_id:
            log.warning("[World] I DIED")
        elif pkt.object_id in self.world.npcs:
            npc = self.world.npcs[pkt.object_id]
            log.info("[World] Mob died: npcId=%d '%s'", npc.npc_id, npc.name or npc.title)

    def _on_target_selected(self, payload: bytes) -> None:
        pkt = TargetSelected.parse(payload)
        log.debug("[World] TargetSelected: objId=0x%X pos=(%d,%d,%d)",
                  pkt.object_id, pkt.x, pkt.y, pkt.z)

    def _on_spawn_item(self, payload: bytes) -> None:
        pkt = SpawnItem.parse(payload)
        self.world.on_spawn_item(pkt)
        log.info("[World] Drop: itemObjId=0x%X itemId=%d count=%d pos=(%d,%d,%d) dropper=0x%X [%dB]",
                 pkt.object_id, pkt.item_id, pkt.count, pkt.x, pkt.y, pkt.z,
                 pkt.dropper_id, len(payload))

    def _on_attack(self, payload: bytes) -> None:
        pkt = Attack.parse(payload)
        is_me_attacking = pkt.attacker_id == self.world.me.object_id
        is_me_target = pkt.target_id == self.world.me.object_id
        if is_me_attacking:
            log.info("[World] I hit objId=0x%X dmg=%d", pkt.target_id, pkt.damage)
        elif is_me_target:
            me = self.world.me
            log.warning("[World] INCOMING dmg=%d from objId=0x%X (my HP: %d/%d = %.0f%%)",
                        pkt.damage, pkt.attacker_id, me.cur_hp, me.max_hp, me.hp_pct)

    # ------------------------------------------------------------------ #
    # Auto-combat
    # ------------------------------------------------------------------ #

    def start_auto_combat(self, combat_range: float = 2000.0) -> None:
        """Start auto-combat loop. Must be called from the asyncio loop thread."""
        if self._auto_combat:
            self.stop_auto_combat()
        self._auto_combat = True
        self._combat_range = combat_range
        self._auto_task = asyncio.ensure_future(self._auto_combat_loop())
        log.info("[BotEngine] Auto-combat started (range=%.0f)", combat_range)

    def stop_auto_combat(self) -> None:
        """Stop auto-combat loop."""
        self._auto_combat = False
        if self._auto_task and not self._auto_task.done():
            self._auto_task.cancel()
        self._auto_task = None
        log.info("[BotEngine] Auto-combat stopped")

    async def _auto_combat_loop(self) -> None:
        log.info("[BotEngine] Auto-combat loop running")
        while self._auto_combat:
            try:
                # Periodic cleanup of dead NPCs (no DeleteObject packets on Teon)
                cleaned = self.world.cleanup_dead(30.0)
                if cleaned:
                    log.debug("[AutoCombat] Cleaned %d dead NPCs from world", cleaned)

                # Always loot any nearby items first (from previous kills etc)
                if self._auto_loot:
                    items_around = self.world.get_items_in_range(self._loot_range)
                    if items_around:
                        looted = await self.loot_nearby_async(self._loot_range)
                        log.info("[AutoCombat] Loot: picked %d items", looted)
                        if looted:
                            await asyncio.sleep(1.0)  # wait for pickups to complete

                mob = self.world.get_nearest_mob(self._combat_range)
                if mob:
                    log.info("[AutoCombat] Target: npcId=%d '%s' objId=0x%X dist=%.0f hp=%.0f%%",
                             mob.npc_id, mob.name or mob.title or '?',
                             mob.object_id, self.world.dist_to(mob), mob.hp_pct)
                    # Step 1: Target the mob via Action (0x04)
                    self.attack(mob.object_id)
                    await asyncio.sleep(0.3)
                    if not self._auto_combat:
                        return
                    # Step 2: Attack via 0x2F actionId=16 (real client attack)
                    self.force_attack()
                    # Wait for the mob to die (max 15 seconds)
                    for i in range(30):
                        await asyncio.sleep(0.5)
                        if not self._auto_combat:
                            return
                        if mob.is_dead or mob.object_id not in self.world.npcs:
                            log.info("[AutoCombat] Mob dead after %.1fs", (i + 1) * 0.5)
                            break
                        # Re-send attack every 1.5s to maintain auto-attack
                        if (i + 1) % 3 == 0:
                            self.attack(mob.object_id)
                            await asyncio.sleep(0.15)
                            self.force_attack()
                        # Check HP — sit to heal if low
                        me = self.world.me
                        if me.max_hp > 0 and me.hp_pct < 30:
                            log.warning("[AutoCombat] HP low (%.0f%%) — sitting to heal",
                                        me.hp_pct)
                            self.cancel_target()
                            self.sit_stand()  # sit
                            await self._wait_heal(70.0)
                            self.sit_stand()  # stand
                            await asyncio.sleep(0.5)
                            break  # re-select target after healing
                    else:
                        log.warning("[AutoCombat] Mob kill timeout (15s) — moving on")
                    # Auto-loot after kill — wait for drop packets, then pick up
                    if self._auto_loot:
                        await asyncio.sleep(1.0)   # wait for SpawnItem packets
                        looted = await self.loot_nearby_async(self._loot_range)
                        if looted:
                            log.info("[AutoCombat] Post-kill loot: picked %d items", looted)
                            await asyncio.sleep(1.0)  # wait for pickups
                    # Check HP before next target — heal if needed
                    me = self.world.me
                    if me.max_hp > 0 and me.hp_pct < 50:
                        log.info("[AutoCombat] HP=%.0f%% after kill — sitting to heal", me.hp_pct)
                        self.sit_stand()  # sit
                        await self._wait_heal(80.0)
                        self.sit_stand()  # stand
                        await asyncio.sleep(0.5)
                    await asyncio.sleep(0.3)   # small pause before next target
                else:
                    # No mobs — try to loot any remaining items
                    if self._auto_loot:
                        looted = await self.loot_nearby_async(self._loot_range)
                        if looted:
                            log.info("[AutoCombat] Idle loot: picked %d items", looted)
                    total = len(self.world.npcs)
                    atk = sum(1 for n in self.world.npcs.values()
                              if n.is_attackable and not n.is_dead)
                    log.info("[AutoCombat] No mobs in range (world_npcs=%d, attackable=%d, range=%.0f)",
                             total, atk, self._combat_range)
                    await asyncio.sleep(1.0)   # no mobs nearby, wait
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("[AutoCombat] Error: %s", exc)
                await asyncio.sleep(1.0)
        log.info("[BotEngine] Auto-combat loop stopped")

    # ------------------------------------------------------------------ #
    # Bot actions (call from scripts or UI)
    # ------------------------------------------------------------------ #

    def attack(self, target_id: int) -> None:
        """Send attack request for target_id.
        Uses CS_Action (0x04) to target, then RequestActionUse-like 0x2F
        with actionId=16 to actually attack (confirmed from real client traffic)."""
        me = self.world.me
        # First call targets (Action 0x04), second call attacks (0x2F actionId=16)
        opcode, payload = cs.build_attack(target_id, me.x, me.y, me.z)
        self.game_proxy.inject_to_server(opcode, payload)
        log.info("[Bot] Attack → objectId=0x%X from=(%d,%d,%d)", target_id, me.x, me.y, me.z)

    def force_attack(self) -> None:
        """Send the actual attack command (0x2F actionId=16) — confirmed from real client."""
        opcode, payload = cs.build_force_attack()
        self.game_proxy.inject_to_server(opcode, payload)
        log.info("[Bot] ForceAttack → 0x2F actionId=16")

    def move_to(self, x: int, y: int, z: int) -> None:
        """Move character to X,Y,Z."""
        me = self.world.me
        opcode, payload = cs.build_move(x, y, z, me.x, me.y, me.z)
        self.game_proxy.inject_to_server(opcode, payload)
        log.info("[Bot] Move → (%d,%d,%d)", x, y, z)

    def use_skill(self, skill_id: int, ctrl: bool = False, shift: bool = False) -> None:
        """Use a skill by ID."""
        opcode, payload = cs.build_use_skill(skill_id, ctrl, shift)
        self.game_proxy.inject_to_server(opcode, payload)
        log.info("[Bot] UseSkill → skillId=%d", skill_id)

    def cancel_target(self) -> None:
        opcode, payload = cs.build_cancel_target()
        self.game_proxy.inject_to_server(opcode, payload)

    def sit_stand(self) -> None:
        """Toggle sit/stand via RequestActionUse (actionId=0)."""
        opcode, payload = cs.build_action_use(action_id=0)
        self.game_proxy.inject_to_server(opcode, payload)
        log.info("[Bot] SitStand → RequestActionUse actionId=0")

    def pickup(self, item_object_id: int) -> None:
        """Pick up item on ground by right-clicking it (CS_Action 0x04).
        This is how the real client picks up items — NOT via 0x48."""
        me = self.world.me
        opcode, payload = cs.build_action(item_object_id, me.x, me.y, me.z)
        self.game_proxy.inject_to_server(opcode, payload)
        log.info("[Bot] Pickup (Action) → objectId=0x%X from=(%d,%d,%d)",
                 item_object_id, me.x, me.y, me.z)

    async def loot_nearby_async(self, max_dist: float = 800.0) -> int:
        """Pick up all ground items within range via right-click (CS_Action).
        Async version with delays between items for walking. Returns count."""
        items = self.world.get_items_in_range(max_dist)
        for item in items:
            self.pickup(item.object_id)
            self.world.ground_items.pop(item.object_id, None)
            if len(items) > 1:
                await asyncio.sleep(0.5)  # wait for character to walk to item
        return len(items)

    def loot_nearby(self, max_dist: float = 800.0) -> int:
        """Pick up all ground items within range via right-click (CS_Action).
        Sync version — sends all pickups at once. Returns count."""
        items = self.world.get_items_in_range(max_dist)
        for item in items:
            self.pickup(item.object_id)
            self.world.ground_items.pop(item.object_id, None)
        return len(items)

    async def _wait_heal(self, target_pct: float = 70.0, max_wait: float = 60.0) -> None:
        """Wait while sitting until HP recovers to target_pct or max_wait expires."""
        start = time.monotonic()
        while time.monotonic() - start < max_wait:
            await asyncio.sleep(1.0)
            me = self.world.me
            if me.max_hp > 0 and me.hp_pct >= target_pct:
                log.info("[AutoCombat] Healed to %.0f%% — resuming", me.hp_pct)
                return
            if not self._auto_combat:
                return
        log.info("[AutoCombat] Heal timeout (%.0fs) — resuming at %.0f%%",
                 max_wait, self.world.me.hp_pct)

    def attack_nearest(self, max_dist: float = 2000.0) -> Optional[Npc]:
        """Find nearest mob and attack it. Returns the target or None."""
        mob = self.world.get_nearest_mob(max_dist)
        if mob:
            self.attack(mob.object_id)
        return mob
