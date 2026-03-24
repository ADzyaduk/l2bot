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
    SpawnItem, Attack, SkillList, ItemList, InventoryUpdate, SkillCoolTime,
    AbnormalStatusUpdate, MagicSkillLaunched, ChangeWaitType,
)
from core.packets import client as cs
from core import game_reference
from collections import Counter

from core.protocol.opcode_detector import OpcodeDetector, NPCINFO_PAYLOAD_SIZE
from engine.combat_profile import CombatProfile, load_profile
from engine.buff_profile import (
    BuffProfile,
    BuffRule,
    default_buff_profile_path,
    load_buff_profile,
    normalize_buff_skill_packet,
    normalize_magic_skill_payload,
    normalize_self_buff_precast,
    normalize_target_cancel_payload,
)
from engine.world import World, Npc, GroundItem

log = logging.getLogger(__name__)

# Buffer all S2C (opcode, payload) until OpcodeDetector assigns handlers, then replay in order.
# Login sends SkillList / UserInfo before the NpcInfo burst; Npc-only 180–210B filter used to drop them.
_MAX_PRE_DETECT_PACKETS = 1200
# After a buff cast, server may send AbnormalStatusUpdate a bit later — avoid instant «missing» recast.
_BUFF_ABNORMAL_GRACE_AFTER_CAST_SEC = 4.0
# Pause after RequestActionUse sit/stand toggle so SC_ChangeWaitType can update me_sitting before the next toggle.
_RECOVERY_TOGGLE_ACK_SEC = 0.4


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
        # idle | in_kill_loop | recovering — for buff pause + diagnostics
        self._combat_phase: str = "idle"
        self._last_incoming_damage_mono: float = 0.0
        self._buff_cast_times: list[float] = []
        self._combat_profile: CombatProfile = load_profile()
        self._rule_last_fire: dict[int, float] = {}
        self._buff_profile: BuffProfile = load_buff_profile()
        self._buff_last_cast: dict[int, float] = {}
        self._buff_task: Optional[asyncio.Task] = None
        self._magic_skill_combat: str = normalize_magic_skill_payload(
            self._combat_profile.magic_skill_payload
        )
        self._magic_skill_buff: str = normalize_magic_skill_payload(
            self._buff_profile.magic_skill_payload
        )
        self._buff_skill_packet: str = normalize_buff_skill_packet(
            self._buff_profile.buff_skill_packet
        )
        self._c2s_target_cancel_payload: str = normalize_target_cancel_payload(
            self._combat_profile.target_cancel_payload
        )
        # Log when AbnormalStatus effect id set for self changes (debug Teon / buff rules).
        self._abnormal_self_logged: frozenset[int] | None = None

        self._log_buff_profile_loaded("startup")

        # Debug: hex dump first N NpcInfo packets to verify parser alignment
        self._npc_debug_count = 0
        self._npc_debug_max = 3

        # Debug: hex dump unhandled packets (first 2 of each opcode)
        self._unhandled_hex_seen: dict[int, int] = {}
        self._unhandled_hex_max = 2

        # Track Die events for post-kill packet analysis
        self._last_die_time: float = 0

        # Packets received before opcode detection (replay in order when handlers exist).
        self._pre_detect_packets: list[tuple[int, bytes]] = []
        # Post-kill recovery: we sent a sit toggle and must stand in finally (even on timeout / stop combat).
        self._recovery_sent_sit_toggle: bool = False

    def start(self) -> None:
        """Hook into GameProxy to receive server packets."""
        self.game_proxy.on_server_packet = self._dispatch
        self.game_proxy.on_new_session = self._on_new_session
        self._detector.reset()
        log.info("[BotEngine] Started — listening for game packets")

    def _on_new_session(self) -> None:
        """Called when game client reconnects — reset opcode detector."""
        if self._buff_task and not self._buff_task.done():
            self._buff_task.cancel()
        self._buff_task = None
        self._buff_last_cast.clear()
        self._handlers.clear()
        self._detector.reset()
        self.world = World()
        self._abnormal_self_logged = None
        self._pre_detect_packets.clear()
        self._npc_debug_count = 0
        self._unhandled_hex_seen.clear()
        self._last_die_time = 0
        self._rule_last_fire.clear()
        self._recovery_sent_sit_toggle = False
        game_reference.clear_session_extras()
        log.info("[BotEngine] New game session — opcode detector reset")

    def stop(self) -> None:
        self._running = False
        if self._buff_task and not self._buff_task.done():
            self._buff_task.cancel()
        self._buff_task = None
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
            # Die vs Die2: Teon SC_Die is 4B (registry 0x68) → maps to Die2 after XOR.
            # Base 0x06 "full" Die must not share a handler that treats every short payload as death.
            opcodes["Die"]:               self._on_die_full,
            opcodes["TargetSelected"]:    self._on_target_selected,
            opcodes["SpawnItem"]:         self._on_spawn_item,
            opcodes["StatusUpdate2"]:     self._on_status_update,
            opcodes["Attack"]:            self._on_attack,
            opcodes["Die2"]:              self._on_die_short,
        }
        sk_op = opcodes.get("SkillList")
        if sk_op is not None:
            self._handlers[sk_op] = self._on_skill_list
        il_op = opcodes.get("ItemList")
        if il_op is not None:
            self._handlers[il_op] = self._on_item_list
        iu_op = opcodes.get("InventoryUpdate")
        if iu_op is not None:
            self._handlers[iu_op] = self._on_inventory_update
        ct_op = opcodes.get("SkillCoolTime")
        if ct_op is not None:
            self._handlers[ct_op] = self._on_skill_cool_time
        ab_op = opcodes.get("AbnormalStatusUpdate")
        if ab_op is not None:
            self._handlers[ab_op] = self._on_abnormal_status_update
        msl_op = opcodes.get("MagicSkillLaunched")
        if msl_op is not None:
            self._handlers[msl_op] = self._on_magic_skill_launched
        cw_op = opcodes.get("ChangeWaitType")
        if cw_op is not None:
            self._handlers[cw_op] = self._on_change_wait_type
        log.info("[BotEngine] Opcodes updated — handlers ready (XOR key=0x%02X)",
                 self._detector.xor_key)

        npc_opcode = opcodes["NpcInfo"]
        buf = self._pre_detect_packets
        pending = len(buf)
        npc_sizes = Counter(len(pld) for op, pld in buf if op == npc_opcode)
        if npc_sizes:
            log.info(
                "[BotEngine] Pre-detect buffer: NpcInfo payloads by size %s (typical ~%dB)",
                dict(sorted(npc_sizes.items())),
                NPCINFO_PAYLOAD_SIZE,
            )
        replayed_handlers = 0
        replayed_npc = 0
        for op, pld in buf:
            h = self._handlers.get(op)
            if not h:
                continue
            try:
                h(pld)
                replayed_handlers += 1
                if op == npc_opcode:
                    replayed_npc += 1
            except Exception:
                pass
        buf.clear()
        n_npcs = len(self.world.npcs)
        n_skills = len(self.world.my_skills)
        log.info(
            "[BotEngine] Pre-detect replay: %d packet(s) with handlers (%d NpcInfo) → "
            "npcs=%d my_skills=%d",
            replayed_handlers,
            replayed_npc,
            n_npcs,
            n_skills,
        )
        if replayed_npc > 0 and n_npcs == 0:
            log.warning(
                "[BotEngine] NpcInfo replay did not populate npcs — check NpcInfo.parse alignment "
                "or payload length (expected ~%dB on Teon)",
                NPCINFO_PAYLOAD_SIZE,
            )
        elif replayed_npc == 0 and pending > 0 and n_npcs == 0:
            log.warning(
                "[BotEngine] No NpcInfo in pre-detect buffer (had %d packets) — enter zone after proxy "
                "or move to refresh spawns",
                pending,
            )
        self._schedule_buff_loop()

    # ------------------------------------------------------------------ #
    # Packet dispatch
    # ------------------------------------------------------------------ #

    async def _dispatch(self, opcode: int, payload: bytes) -> None:
        # Always feed detector (no-op once ready)
        self._detector.feed(opcode, len(payload))

        if not self._handlers and len(self._pre_detect_packets) < _MAX_PRE_DETECT_PACKETS:
            self._pre_detect_packets.append((opcode, payload))

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

    def _on_die_short(self, payload: bytes) -> None:
        """4-byte slot (Die2 / registry SC_Die): reliable for *player* death; not for NPC world state.

        Teon often maps other 4B notifies here or broadcasts ids that are not «this unit just died».
        NPC death is taken from StatusUpdate (HP≤0), SpawnItem dropper, and full Die only."""
        if len(payload) != 4:
            log.debug(
                "[BotEngine] Die2 ignored: expected 4B payload, got %dB (hex: %s)",
                len(payload),
                payload[: min(16, len(payload))].hex(" "),
            )
            return
        pkt = Die.parse(payload)
        if pkt.object_id == 0:
            return
        if pkt.object_id == self.world.me.object_id:
            self._apply_die(payload)
            return
        if log.isEnabledFor(logging.DEBUG) and pkt.object_id in self.world.npcs:
            n = self.world.npcs[pkt.object_id]
            log.debug(
                "[Die2] not applied to world (npcId=%d objId=0x%X) — use HP/drop/full Die",
                n.npc_id,
                pkt.object_id,
            )

    def _on_die_full(self, payload: bytes) -> None:
        """Standard L2J Die (0x06): structure extends well past objectId; ignore tiny payloads."""
        if len(payload) < 8:
            log.debug(
                "[BotEngine] Die (full) ignored: expected >=8B, got %dB — likely wrong opcode mapping",
                len(payload),
            )
            return
        self._apply_die(payload)

    def _apply_die(self, payload: bytes) -> None:
        pkt = Die.parse(payload)
        if pkt.object_id == 0:
            return
        self.world.on_die(pkt)
        self._last_die_time = time.monotonic()
        if pkt.object_id == self.world.me.object_id:
            log.warning("[World] I DIED")
        elif pkt.object_id in self.world.npcs:
            npc = self.world.npcs[pkt.object_id]
            log.info("[World] Mob died: npcId=%d '%s'", npc.npc_id, npc.name or npc.title)

    def _on_target_selected(self, payload: bytes) -> None:
        pkt = TargetSelected.parse(payload)
        self.world.me.target_id = pkt.object_id
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
            self._last_incoming_damage_mono = time.monotonic()
            log.warning(
                "[World] INCOMING dmg=%d from objId=0x%X (my HP: %d/%d eff_max=%d = %.0f%% safe)",
                pkt.damage,
                pkt.attacker_id,
                me.cur_hp,
                me.max_hp,
                me.effective_max_hp(),
                me.hp_pct_safe,
            )

    def _on_skill_list(self, payload: bytes) -> None:
        pkt = SkillList.parse(payload)
        self.world.on_skill_list(pkt.skills)
        log.info("[World] SkillList: %d entries", len(self.world.my_skills))

    def _on_item_list(self, payload: bytes) -> None:
        pkt = ItemList.parse(payload)
        self.world.on_item_list(pkt)
        log.info("[World] ItemList: %d slots (show_window=%s)", len(pkt.items), pkt.show_window)

    def _on_inventory_update(self, payload: bytes) -> None:
        pkt = InventoryUpdate.parse(payload)
        self.world.on_inventory_update(pkt)
        if pkt.items:
            log.info("[World] InventoryUpdate: %d row(s)", len(pkt.items))

    def _on_skill_cool_time(self, payload: bytes) -> None:
        pkt = SkillCoolTime.parse(payload)
        self.world.on_skill_cool_time(pkt.rows)
        if pkt.rows:
            log.debug("[World] SkillCoolTime: %d rows", len(pkt.rows))

    def _on_magic_skill_launched(self, payload: bytes) -> None:
        pkt = MagicSkillLaunched.parse(payload)
        self.world.on_magic_skill_launched(pkt)
        me = self.world.me.object_id
        if me and pkt.caster_id == me and pkt.skill_id > 0:
            log.debug(
                "[World] MagicSkillLaunched self skillId=%d lvl=%d",
                pkt.skill_id,
                pkt.skill_level,
            )

    def _on_change_wait_type(self, payload: bytes) -> None:
        pkt = ChangeWaitType.parse(payload)
        sit_raw = self._combat_profile.recovery_change_wait_type_sit_raw
        self.world.on_change_wait_type(pkt.object_id, pkt.wait_type, sit_raw=sit_raw)

    def _on_abnormal_status_update(self, payload: bytes) -> None:
        pkt = AbnormalStatusUpdate.parse(payload)
        # Unrecognized short 0x7F decodes to empty fallback (oid 0) → would map to self and spam rebuff.
        # Structured «oid + count 0» packets set explicit_empty and must clear buff tracking (cancel).
        if len(payload) <= 8 and not pkt.effects and not pkt.explicit_empty:
            log.debug(
                "[World] AbnormalStatus: skip short non-authoritative empty payload (%d bytes)",
                len(payload),
            )
            return
        self.world.on_abnormal_status_update(
            pkt.object_id, pkt.effects, explicit_empty=pkt.explicit_empty
        )
        log.debug(
            "[World] AbnormalStatus: objId=0x%X effects=%d",
            pkt.object_id, len(pkt.effects),
        )
        me = self.world.me.object_id
        if me and self.world.abnormal_reported_for_object(me):
            sids = frozenset(self.world.abnormal_skill_ids_for_object(me))
            if sids != self._abnormal_self_logged:
                self._abnormal_self_logged = sids
                log.info(
                    "[World] AbnormalStatus self → effect_skill_ids=%s (%d rows parsed, %d bytes)",
                    sorted(sids),
                    len(pkt.effects),
                    len(payload),
                )

    def set_combat_profile(self, profile: CombatProfile) -> None:
        self._combat_profile = profile
        self._rule_last_fire.clear()
        self._c2s_target_cancel_payload = normalize_target_cancel_payload(profile.target_cancel_payload)
        self._magic_skill_combat = normalize_magic_skill_payload(profile.magic_skill_payload)

    def set_buff_profile(self, profile: BuffProfile) -> None:
        self._buff_profile = profile
        self._buff_last_cast.clear()
        self._buff_cast_times.clear()
        self._magic_skill_buff = normalize_magic_skill_payload(profile.magic_skill_payload)
        self._buff_skill_packet = normalize_buff_skill_packet(profile.buff_skill_packet)
        self._log_buff_profile_loaded("apply")

    def _log_buff_profile_loaded(self, reason: str) -> None:
        path = default_buff_profile_path()
        exists = path.is_file()
        log.info(
            "[BuffProfile] %s file=%s exists=%s buff_packet=0x%s magic_skill_payload=%s rules=%d",
            reason,
            path,
            exists,
            self._buff_skill_packet,
            self._magic_skill_buff,
            len(self._buff_profile.rules),
        )

    def _schedule_buff_loop(self) -> None:
        if self._buff_task and not self._buff_task.done():
            return
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        self._buff_task = loop.create_task(self._buff_maintenance_loop())

    async def _buff_maintenance_loop(self) -> None:
        log.info(
            "[BotEngine] Buff maintenance loop started (buff C2S 0x%s, 0x39 body style=%s)",
            self._buff_skill_packet,
            self._magic_skill_buff,
        )
        try:
            while True:
                tick = max(0.25, float(self._buff_profile.maintenance_tick_sec))
                await asyncio.sleep(tick)
                try:
                    await self._buff_maintenance_tick()
                except Exception:
                    log.exception("[BotEngine] Buff maintenance tick failed")
        except asyncio.CancelledError:
            log.debug("[BotEngine] Buff maintenance loop cancelled")
            raise

    def _buff_pause_for_auto_combat(self) -> bool:
        p = self._buff_profile
        if not p.pause_while_auto_combat_engaged:
            return False
        if not self._auto_combat:
            return False
        if self._combat_phase == "in_kill_loop":
            return True
        if self._hostile_target_alive():
            return True
        return False

    def _hostile_target_alive(self) -> bool:
        tid = self.world.me.target_id
        if not tid:
            return False
        n = self.world.npcs.get(tid)
        if not n or not n.is_attackable:
            return False
        return not n.looks_eliminated()

    def _allow_post_kill_recovery_sit(self) -> bool:
        prof = self._combat_profile
        if prof.never_sit_while_target and self._hostile_target_alive():
            log.info("[AutoCombat] Skip post-kill sit: hostile target still selected")
            return False
        gate = prof.incoming_damage_sit_block_sec
        if gate > 0 and (time.monotonic() - self._last_incoming_damage_mono) < gate:
            log.info(
                "[AutoCombat] Skip post-kill sit: incoming damage within %.1fs",
                gate,
            )
            return False
        return True

    def _record_buff_cast(self) -> None:
        now = time.monotonic()
        self._buff_cast_times.append(now)
        self._buff_cast_times = [t for t in self._buff_cast_times if now - t < 60.5]

    def _self_rebuff_buff_presence(self, match_set: set[int], effects: set[int]) -> bool | None:
        """Whether monitored buffs are on self: True/False, or None if unknown (avoid rebuff spam)."""
        if bool(effects & match_set):
            return True
        parts = [self.world.buff_present_merged_self(sid) for sid in match_set]
        if any(p is True for p in parts):
            return True
        if parts and all(p is False for p in parts):
            return False
        return None

    def _buff_need_cast(
        self,
        *,
        buff_present: bool | None,
        now: float,
        last: float,
        interval: float,
        grace: bool,
        party_timer_only: bool,
    ) -> bool:
        """Decide cast for one rebuff rule (min_retry already enforced by caller)."""
        if party_timer_only:
            return (last == 0.0) or (now >= last + interval)
        if buff_present is True:
            return now >= last + interval
        if buff_present is False:
            if grace:
                return now >= last + interval
            return True
        # Unknown — only periodic attempts, not every tick
        return (last == 0.0) or (now >= last + interval)

    async def _buff_maintenance_tick(self) -> None:
        prof = self._buff_profile
        if not prof.enabled or not prof.rules:
            return
        if self._buff_pause_for_auto_combat():
            return
        me = self.world.me
        if not me.object_id:
            return
        if me.max_hp > 0 and me.cur_hp <= 0:
            return
        now = time.monotonic()
        cap = prof.max_buff_casts_per_minute
        if cap > 0:
            self._buff_cast_times = [t for t in self._buff_cast_times if now - t < 60.0]
            if len(self._buff_cast_times) >= int(cap):
                return
        for idx, rule in enumerate(prof.rules):
            if not rule.enabled or rule.skill_id <= 0:
                continue
            if rule.skill_id in self.world.passive_skill_ids:
                continue
            if self.world.my_skills and rule.skill_id not in self.world.my_skills:
                pass
            if not self.world.is_skill_ready(rule.skill_id):
                continue
            last = self._buff_last_cast.get(idx, 0.0)
            if now - last < max(0.0, rule.min_retry_sec):
                continue
            target_oid = self._buff_resolve_target_oid(rule)
            if target_oid is None or target_oid == 0:
                continue
            effects = self.world.abnormal_skill_ids_for_object(target_oid)
            interval = max(1.0, rule.interval_sec)
            if rule.rebuff_if_missing and rule.skill_id > 0:
                eff_abn = rule.check_buff_skill_id if rule.check_buff_skill_id > 0 else rule.skill_id
            else:
                eff_abn = rule.check_buff_skill_id if rule.check_buff_skill_id > 0 else 0
            if eff_abn > 0:
                if rule.abnormal_match_ids:
                    match_set = set(rule.abnormal_match_ids)
                else:
                    match_set = {eff_abn}
                grace = (
                    last > 0
                    and (now - last) < _BUFF_ABNORMAL_GRACE_AFTER_CAST_SEC
                )
                party_timer_only = target_oid != me.object_id and not self.world.abnormal_reported_for_object(
                    target_oid
                )
                if party_timer_only:
                    buff_present = None
                elif target_oid == me.object_id:
                    # Self: merge Abnormal + MagicSkillLaunched / SkillList (Teon often omits toggles in Abnormal).
                    buff_present = self._self_rebuff_buff_presence(match_set, effects)
                elif self.world.abnormal_reported_for_object(target_oid):
                    buff_present = bool(effects & match_set)
                else:
                    buff_present = None
                need_cast = self._buff_need_cast(
                    buff_present=buff_present,
                    now=now,
                    last=last,
                    interval=interval,
                    grace=grace,
                    party_timer_only=party_timer_only,
                )
            else:
                # Timer-only: first run (last==0) casts once, then every interval_sec.
                need_cast = (last == 0.0) or (now >= last + interval)
            if not need_cast:
                continue
            if rule.target_mode == "self":
                # In-game, auras like Defence Aura need no target; C2S may still care if *another* object is targeted.
                if rule.skip_precast_for_self:
                    precast = "none"
                else:
                    precast = self._buff_profile.self_buff_before_cast
                mode = normalize_self_buff_precast(precast)
                need_delay = False
                tid = me.target_id
                precast_note = ""
                if mode == "auto":
                    # Defense Aura (91) and similar: with target_id=0, real client often casts 0x39 only.
                    # 0x04 on self first makes Teon disconnect for many users — only precast when we *see* a foreign target.
                    if tid == me.object_id:
                        precast_note = "already_self → 0x39 only"
                    elif tid != 0:
                        self.target_object(me.object_id, shift=False)
                        need_delay = True
                        precast_note = "0x04_self (had foreign target 0x%X)" % tid
                    else:
                        precast_note = "target_id=0 → 0x39 only (no Action on self)"
                elif mode == "target_self":
                    self.target_object(me.object_id, shift=False)
                    need_delay = True
                    precast_note = "0x04_self forced"
                else:
                    precast_note = "none"
                log.info(
                    "[Buff] precast mode=%s me=0x%X target_id=0x%X → %s",
                    mode, me.object_id, tid, precast_note,
                )
                if need_delay:
                    await asyncio.sleep(max(0.05, prof.self_buff_precast_delay_sec))
                    if not self.world.is_skill_ready(rule.skill_id):
                        continue
            else:
                self.target_object(target_oid, shift=rule.target_shift_click)
                await asyncio.sleep(0.3)
                if not self.world.is_skill_ready(rule.skill_id):
                    continue
            self.use_skill(
                rule.skill_id,
                ctrl=rule.skill_force_ctrl,
                shift=rule.skill_force_shift,
                for_buff=True,
            )
            self._buff_last_cast[idx] = now
            self._record_buff_cast()
            log.info(
                "[Buff] Rule #%d skillId=%d target=0x%X (mode=%s)",
                idx, rule.skill_id, target_oid, rule.target_mode,
            )
            await asyncio.sleep(max(0.05, prof.post_skill_delay))

    def _buff_resolve_target_oid(self, rule: BuffRule) -> Optional[int]:
        me = self.world.me
        if rule.target_mode == "self":
            return me.object_id
        if rule.target_mode == "current_target":
            tid = me.target_id
            return tid if tid else None
        if rule.target_mode == "manual":
            return rule.target_object_id if rule.target_object_id else None
        return me.object_id

    def _npc_fightable(self, oid: int) -> bool:
        """True if oid is still a valid attack target in world (fresh dict lookup)."""
        if oid in self.world.dead_ids:
            return False
        wn = self.world.npcs.get(oid)
        if not wn or not wn.is_attackable:
            return False
        if wn.looks_eliminated():
            return False
        return True

    def _target_eliminated(self, oid: int) -> bool:
        """Mob gone from world, marked dead, or 0 HP — safe to loot / pick next target."""
        if oid in self.world.dead_ids:
            return True
        wn = self.world.npcs.get(oid)
        if not wn:
            return True
        return wn.looks_eliminated()

    async def _maybe_combat_rules(self, mob: Optional[Npc]) -> None:
        prof = self._combat_profile
        if not prof.rules:
            return
        me = self.world.me
        in_combat = mob is not None
        now = time.monotonic()
        for idx, rule in enumerate(prof.rules):
            if rule.only_in_combat and not in_combat:
                continue
            if rule.hp_below_pct > 0:
                if me.effective_max_hp() <= 0 or me.hp_pct_safe >= rule.hp_below_pct:
                    continue
            if rule.mp_below_pct > 0:
                if me.effective_max_mp() <= 0 or me.mp_pct_safe >= rule.mp_below_pct:
                    continue
            if rule.hp_min_pct > 0:
                if me.effective_max_hp() <= 0 or me.hp_pct_safe < rule.hp_min_pct:
                    continue
            if rule.mp_min_pct > 0:
                if me.effective_max_mp() <= 0 or me.mp_pct_safe < rule.mp_min_pct:
                    continue
            if rule.cooldown_sec > 0:
                last = self._rule_last_fire.get(idx, 0.0)
                if now - last < rule.cooldown_sec:
                    continue
            if rule.rebuff_missing_skill_id > 0:
                if rule.rebuff_missing_skill_id in self.world.abnormal_buff_skill_ids:
                    continue
            if rule.kind == "skill" and rule.skill_id > 0:
                if rule.skill_id in self.world.passive_skill_ids:
                    log.debug(
                        "[AutoCombat] Rule #%d skillId=%d is passive — cannot cast",
                        idx, rule.skill_id,
                    )
                    continue
                if self.world.my_skills and rule.skill_id not in self.world.my_skills:
                    log.warning(
                        "[AutoCombat] Rule #%d skillId=%d not in SkillList — check id; trying anyway",
                        idx, rule.skill_id,
                    )
                if not self.world.is_skill_ready(rule.skill_id):
                    log.debug(
                        "[AutoCombat] Rule #%d skillId=%d on cooldown",
                        idx, rule.skill_id,
                    )
                    continue
                self.use_skill(rule.skill_id)
                self._rule_last_fire[idx] = now
                log.info("[AutoCombat] Rule #%d skillId=%d", idx, rule.skill_id)
                await asyncio.sleep(prof.post_skill_delay)
                return
            if rule.kind == "item" and rule.item_id > 0:
                oid = self.world.object_id_for_item_template(rule.item_id)
                if oid is None:
                    log.debug(
                        "[AutoCombat] Item rule #%d templateId=%d — no objectId (open inv for ItemList)",
                        idx, rule.item_id,
                    )
                    continue
                self.use_item(oid)
                self._rule_last_fire[idx] = now
                log.info("[AutoCombat] Rule #%d useItem objId=0x%X template=%d", idx, oid, rule.item_id)
                await asyncio.sleep(prof.post_skill_delay)
                return

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
        self._combat_phase = "idle"
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

                prof = self._combat_profile
                # Always loot any nearby items first (from previous kills etc)
                if prof.auto_loot:
                    items_around = self.world.get_items_in_range(prof.loot_range)
                    if items_around:
                        looted = await self.loot_nearby_async(
                            prof.loot_range,
                            rounds=2,
                            max_attempts=10,
                            delay_sec=max(0.05, prof.idle_loot_item_delay_sec),
                        )
                        log.info("[AutoCombat] Loot: %d pickup attempts", looted)
                        if looted:
                            await asyncio.sleep(max(0.05, prof.open_combat_pre_loot_sleep_sec))

                mob = self.world.get_nearest_mob(self._combat_range)
                if mob:
                    # Always resolve by objectId — NpcInfo replaces dict entries, stale mob refs never update.
                    target_oid = mob.object_id
                    log.info("[AutoCombat] Target: npcId=%d '%s' objId=0x%X dist=%.0f hp=%.0f%%",
                             mob.npc_id, mob.name or mob.title or '?',
                             target_oid, self.world.dist_to(mob), mob.hp_pct)
                    # Step 1: Target the mob via Action (0x04)
                    self.attack(target_oid)
                    await asyncio.sleep(self._combat_profile.post_target_delay)
                    if not self._auto_combat:
                        return
                    await self._maybe_combat_rules(self.world.npcs.get(target_oid))
                    if not self._auto_combat:
                        return
                    # Step 2: Attack via 0x2F actionId=16 (real client attack)
                    self.force_attack()
                    kill_tick = max(0.05, prof.kill_poll_tick_sec)
                    kill_max_sec = max(1.0, prof.kill_timeout_sec)
                    reattack_sec = max(0.2, prof.reattack_interval_sec)
                    reattack_sleep = max(0.05, prof.reattack_action_sleep_sec)
                    t0 = time.monotonic()
                    last_reattack = t0
                    self._combat_phase = "in_kill_loop"
                    try:
                        while self._auto_combat:
                            if self._target_eliminated(target_oid):
                                log.info(
                                    "[AutoCombat] Mob dead or gone after %.2fs — loot then next",
                                    time.monotonic() - t0,
                                )
                                break
                            if time.monotonic() - t0 >= kill_max_sec:
                                log.warning(
                                    "[AutoCombat] Kill timeout (%.0fs) — still no death from server; "
                                    "giving up this target (NpcInfo/Die may be missing)",
                                    kill_max_sec,
                                )
                                break
                            now = time.monotonic()
                            if now - last_reattack >= reattack_sec:
                                if not self._npc_fightable(target_oid):
                                    log.info("[AutoCombat] Target no longer fightable — stop re-attacking")
                                    break
                                self.attack(target_oid)
                                await asyncio.sleep(reattack_sleep)
                                await self._maybe_combat_rules(self.world.npcs.get(target_oid))
                                self.force_attack()
                                last_reattack = time.monotonic()
                            await asyncio.sleep(kill_tick)
                    finally:
                        self._combat_phase = "idle"
                    # Drop target so we do not stay glued to a corpse if HP/death packets lag.
                    self.cancel_target()
                    # Auto-loot after kill — wait for drop packets, then pick up
                    if prof.auto_loot:
                        await asyncio.sleep(max(0.05, prof.post_kill_spawn_wait_sec))
                        looted = await self.loot_nearby_async(
                            prof.loot_range,
                            rounds=2,
                            max_attempts=12,
                            delay_sec=max(0.05, prof.post_kill_loot_item_delay_sec),
                        )
                        if looted:
                            log.info("[AutoCombat] Post-kill loot: %d pickup attempts", looted)
                            await asyncio.sleep(max(0.05, prof.post_kill_loot_after_sleep_sec))
                    # Check HP before next target — regen if needed
                    me = self.world.me
                    if (
                        prof.post_kill_sit_enabled
                        and self._allow_post_kill_recovery_sit()
                        and me.effective_max_hp() > 0
                        and me.hp_pct_safe < prof.post_kill_sit_hp_below_pct
                    ):
                        log.info(
                            "[AutoCombat] HP=%.0f%% after kill (< %.0f%%) — sitting to recover",
                            me.hp_pct_safe,
                            prof.post_kill_sit_hp_below_pct,
                        )
                        self._combat_phase = "recovering"
                        self._recovery_sent_sit_toggle = False
                        try:
                            # CS_RequestActionUse(0) toggles sit/stand; without SC_ChangeWaitType we can
                            # double-toggle (e.g. already sitting → first packet stands). See docs/recovery-sit-stand.md
                            await self._ensure_sitting_for_recovery()
                            try:
                                await self._wait_recovery(prof.post_kill_stand_hp_pct)
                            finally:
                                await self._ensure_standing_after_recovery()
                        finally:
                            self._recovery_sent_sit_toggle = False
                            self._combat_phase = "idle"
                        await asyncio.sleep(max(0.05, prof.post_kill_recovery_after_stand_sec))
                    await asyncio.sleep(max(0.05, prof.between_targets_sleep_sec))
                else:
                    # No mobs — try to loot any remaining items
                    if prof.auto_loot:
                        looted = await self.loot_nearby_async(
                            prof.loot_range,
                            rounds=2,
                            max_attempts=8,
                            delay_sec=max(0.05, prof.idle_loot_item_delay_sec),
                        )
                        if looted:
                            log.info("[AutoCombat] Idle loot: %d pickup attempts", looted)
                    total = len(self.world.npcs)
                    atk = sum(1 for n in self.world.npcs.values()
                              if n.is_attackable and not n.is_dead)
                    log.info("[AutoCombat] No mobs in range (world_npcs=%d, attackable=%d, range=%.0f)",
                             total, atk, self._combat_range)
                    await asyncio.sleep(max(0.2, prof.idle_no_mobs_sleep_sec))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("[AutoCombat] Error: %s", exc)
                await asyncio.sleep(1.0)
        log.info("[BotEngine] Auto-combat loop stopped")

    # ------------------------------------------------------------------ #
    # Bot actions (call from scripts or UI)
    # ------------------------------------------------------------------ #

    def target_object(self, object_id: int, *, shift: bool = False) -> None:
        """Select target via CS_Action only (no force-attack). Use shift=True for allies / buff targets."""
        me = self.world.me
        opcode, payload = cs.build_action(object_id, me.x, me.y, me.z, shift=shift)
        self.game_proxy.inject_to_server(opcode, payload)
        log.info("[Bot] Target → objectId=0x%X shift=%s", object_id, shift)

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

    def use_item(self, object_id: int, ctrl: bool = False) -> None:
        """Use inventory item by world objectId (from ItemList)."""
        opcode, payload = cs.build_use_item(object_id, ctrl)
        self.game_proxy.inject_to_server(opcode, payload)
        log.info("[Bot] UseItem → objectId=0x%X", object_id)

    def use_skill(
        self,
        skill_id: int,
        ctrl: bool = False,
        shift: bool = False,
        *,
        for_buff: bool = False,
    ) -> None:
        """Use a skill by ID. Combat: 0x39 + CombatProfile layout. Buff: BuffProfile buff_skill_packet (0x39 or 0x2F Teon)."""
        if for_buff and self._buff_skill_packet == "2f":
            opcode, payload = cs.build_shortcut_skill_use(skill_id, ctrl, shift)
            self.game_proxy.inject_to_server(opcode, payload)
            log.info(
                "[Bot] UseSkill → skillId=%d 0x2F len=%d hex=%s (buff shortcut)",
                skill_id,
                len(payload),
                payload.hex(),
            )
            return
        style = self._magic_skill_buff if for_buff else self._magic_skill_combat
        opcode, payload = cs.build_use_skill(skill_id, ctrl, shift, payload_style=style)
        self.game_proxy.inject_to_server(opcode, payload)
        log.info(
            "[Bot] UseSkill → skillId=%d 0x39 style=%s len=%d hex=%s (%s)",
            skill_id,
            style,
            len(payload),
            payload.hex(),
            "buff" if for_buff else "combat",
        )

    def cancel_target(self) -> None:
        self.world.me.target_id = 0
        opcode, payload = cs.build_cancel_target(payload_style=self._c2s_target_cancel_payload)
        self.game_proxy.inject_to_server(opcode, payload)
        log.info(
            "[Bot] RequestTargetCancel (0x37) style=%s len=%d hex=%s",
            self._c2s_target_cancel_payload,
            len(payload),
            payload.hex(),
        )

    def sit_stand(self) -> None:
        """Toggle sit/stand via RequestActionUse (actionId=0)."""
        opcode, payload = cs.build_action_use(action_id=0)
        self.game_proxy.inject_to_server(opcode, payload)
        log.info("[Bot] SitStand → RequestActionUse actionId=0")

    async def _ensure_sitting_for_recovery(self) -> None:
        """Send at most one sit toggle if we believe we are standing (avoids standing→toggle→stand bugs)."""
        me = self.world.me
        if me.me_sitting is True:
            return
        self.sit_stand()
        self._recovery_sent_sit_toggle = True
        await asyncio.sleep(_RECOVERY_TOGGLE_ACK_SEC)

    async def _ensure_standing_after_recovery(self) -> None:
        """Undo sit after regen: use server sit flag when known, else undo our single recovery toggle."""
        me = self.world.me
        need_toggle = False
        if me.me_sitting is True:
            need_toggle = True
        elif me.me_sitting is None and self._recovery_sent_sit_toggle:
            need_toggle = True
        if not need_toggle:
            return
        self.sit_stand()
        await asyncio.sleep(_RECOVERY_TOGGLE_ACK_SEC)

    def pickup(self, item_object_id: int) -> None:
        """Pick up item on ground by right-clicking it (CS_Action 0x04).
        This is how the real client picks up items — NOT via 0x48."""
        me = self.world.me
        opcode, payload = cs.build_action(item_object_id, me.x, me.y, me.z)
        self.game_proxy.inject_to_server(opcode, payload)
        log.info("[Bot] Pickup (Action) → objectId=0x%X from=(%d,%d,%d)",
                 item_object_id, me.x, me.y, me.z)

    async def loot_nearby_async(
        self,
        max_dist: float = 800.0,
        rounds: int = 4,
        *,
        max_attempts: int = 24,
        delay_sec: float = 0.28,
    ) -> int:
        """Pick up ground items via CS_Action. Multi-pass for late drops.
        Caps attempts so stale objectIds in world do not burn seconds per item."""
        picked = 0
        cap = max(1, max_attempts)
        pause = max(0.05, delay_sec)
        for _ in range(max(1, rounds)):
            items = self.world.get_items_in_range(max_dist)
            if not items:
                await asyncio.sleep(0.12)
                continue
            for item in items:
                if picked >= cap:
                    return picked
                self.pickup(item.object_id)
                picked += 1
                await asyncio.sleep(pause)
            await asyncio.sleep(0.12)
        return picked

    def loot_nearby(self, max_dist: float = 800.0) -> int:
        """Sync pickup burst — still avoids optimistic ground_items.pop (server is source of truth)."""
        items = self.world.get_items_in_range(max_dist)
        for item in items:
            self.pickup(item.object_id)
        return len(items)

    async def _wait_recovery(self, target_hp_pct: float) -> None:
        """Wait while sitting until HP >= target_hp_pct and (if configured) MP >= recovery_stand_mp_pct."""
        prof = self._combat_profile
        max_wait = prof.recovery_max_wait_sec
        mp_gate = prof.mp_recovery_enabled()
        start = time.monotonic()
        while time.monotonic() - start < max_wait:
            await asyncio.sleep(1.0)
            if not self._auto_combat:
                return
            me = self.world.me
            hp_ok = me.hp_pct_safe >= target_hp_pct
            mp_ok = (
                not mp_gate
                or me.effective_max_mp() <= 0
                or me.mp_pct_safe >= prof.recovery_stand_mp_pct
            )
            if hp_ok and mp_ok:
                log.info(
                    "[AutoCombat] Recovery done — HP=%.0f%% MP=%.0f%% — resuming",
                    me.hp_pct_safe,
                    me.mp_pct_safe,
                )
                return
        log.info(
            "[AutoCombat] Recovery timeout (%.0fs) — resuming HP=%.0f%% MP=%.0f%%",
            max_wait,
            self.world.me.hp_pct_safe,
            self.world.me.mp_pct_safe,
        )

    def attack_nearest(self, max_dist: float = 2000.0) -> Optional[Npc]:
        """Find nearest mob and attack it. Returns the target or None."""
        mob = self.world.get_nearest_mob(max_dist)
        if mob:
            self.attack(mob.object_id)
        return mob
