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
from typing import Callable, Optional

from core.proxy.game_proxy import GameProxyServer
from core.packets.server import (
    UserInfo, NpcInfo, DeleteObject, StatusUpdate, MoveToPoint, Die, TargetSelected,
    SpawnItem, Attack, SkillList, ItemList, InventoryUpdate, SkillCoolTime,
    AbnormalStatusUpdate, MagicSkillLaunched, ChangeWaitType,
    PartySpelled,
    PartySmallWindowAdd,
    PartySmallWindowAll,
    PartySmallWindowDelete,
    ShortBuffStatusUpdate,
)
from core.packets import client as cs
from core import game_reference
from collections import Counter

from core.protocol.opcode_detector import OpcodeDetector, NPCINFO_PAYLOAD_SIZE
from engine.character_config import resolve_buff_profile_read_path
from engine.combat_profile import CombatProfile, load_profile
from engine.buff_profile import (
    BuffProfile,
    BuffRule,
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
_RECOVERY_TOGGLE_ACK_SEC = 0.5
# Full SC_UserInfo on Interlude/Teon is hundreds of bytes. Short packets on the same
# session opcode are opcode-detector collisions — parsing them zeros objectId/name and breaks injects.
_MIN_SC_USERINFO_PAYLOAD = 100


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
        self._disk_profile_key: str | None = None
        self._combat_profile: CombatProfile = load_profile(None)
        self._rule_last_fire: dict[int, float] = {}
        self._buff_profile: BuffProfile = load_buff_profile(None)
        # BotCore wires this to refresh Auto combat / Buffs tabs after UserInfo.
        self.profile_tabs_refresh: Optional[Callable[[], None]] = None
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
        self._combat_skill_packet: str = normalize_buff_skill_packet(
            self._combat_profile.combat_skill_packet
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
        self._auto_combat_last_target_oid: int = 0
        self._combat_skill_last_cast: dict[int, float] = {}
        self._move_before_target_warned: bool = False
        # Combat anchor (x,y,z) set when auto-combat starts; optional leash in World.pick_auto_combat_target.
        self._combat_anchor: tuple[int, int, int] | None = None
        self._no_mob_anchor_since: float | None = None

    def start(self) -> None:
        """Hook into GameProxy to receive server packets."""
        self.game_proxy.on_server_packet = self._dispatch
        self.game_proxy.on_new_session = self._on_new_session
        self.game_proxy.on_game_connection_lost = self._on_game_connection_lost
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
        self._auto_combat_last_target_oid = 0
        self._combat_skill_last_cast.clear()
        self._move_before_target_warned = False
        self._combat_anchor = None
        self._no_mob_anchor_since = None
        self._disk_profile_key = None
        self.set_combat_profile(load_profile(None))
        self.set_buff_profile(load_buff_profile(None))
        self._log_buff_profile_loaded("new_session")
        game_reference.clear_session_extras()
        log.info("[BotEngine] New game session — opcode detector reset")

    def _on_game_connection_lost(self) -> None:
        """Game TCP closed (client or server leg) — stop bot activity that would spam injects."""
        log.info("[BotEngine] Game connection lost — stopping auto-combat and buff loop")
        self.stop_auto_combat()
        if self._buff_task and not self._buff_task.done():
            self._buff_task.cancel()
        self._buff_task = None

    def stop(self) -> None:
        self._running = False
        if self._buff_task and not self._buff_task.done():
            self._buff_task.cancel()
        self._buff_task = None
        self.game_proxy.on_server_packet = None
        self.game_proxy.on_new_session = None
        self.game_proxy.on_game_connection_lost = None
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
        ps_op = opcodes.get("PartySpelled")
        if ps_op is not None:
            self._handlers[ps_op] = self._on_party_spelled
        pwa = opcodes.get("PartySmallWindowAll")
        if pwa is not None:
            self._handlers[pwa] = self._on_party_small_window_all
        pwad = opcodes.get("PartySmallWindowAdd")
        if pwad is not None:
            self._handlers[pwad] = self._on_party_small_window_add
        pwdd = opcodes.get("PartySmallWindowDelete")
        if pwdd is not None:
            self._handlers[pwdd] = self._on_party_small_window_delete
        sb_op = opcodes.get("ShortBuffStatusUpdate")
        if sb_op is not None:
            self._handlers[sb_op] = self._on_short_buff_status_update
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
        if len(payload) < _MIN_SC_USERINFO_PAYLOAD:
            log.debug(
                "[BotEngine] Skip UserInfo handler: payload too short (%d B, need ≥%d) — wrong S2C type for this opcode",
                len(payload),
                _MIN_SC_USERINFO_PAYLOAD,
            )
            return
        pkt = UserInfo.parse(payload)
        if pkt.object_id == 0 or not (pkt.name or "").strip():
            log.debug(
                "[BotEngine] Skip UserInfo apply: empty objectId or name after parse (%d B) — likely malformed",
                len(payload),
            )
            return
        self.world.on_user_info(pkt)
        me = self.world.me
        log.info("[World] Me: '%s' objId=0x%X lvl=%d  HP:%d/%d  MP:%d/%d  pos=(%d,%d,%d)",
                 me.name, me.object_id, pkt.level, me.cur_hp, me.max_hp,
                 me.cur_mp, me.max_mp, me.x, me.y, me.z)
        disk_key = me.name or ""
        if disk_key != self._disk_profile_key:
            cp = load_profile(character_name=disk_key)
            bp = load_buff_profile(character_name=disk_key)
            self.set_combat_profile(cp)
            self.set_buff_profile(bp)
            self._disk_profile_key = disk_key
            log.info(
                "[BotEngine] Loaded per-character profiles (key=%r) — see config/characters/",
                disk_key or "_",
            )
            self._log_buff_profile_loaded("character")
            self._notify_profile_tabs_refresh()

    def _notify_profile_tabs_refresh(self) -> None:
        cb = self.profile_tabs_refresh
        if not cb:
            return
        try:
            cb()
        except Exception:
            log.exception("[BotEngine] profile_tabs_refresh failed")

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
            self.world.register_attacker_on_me(pkt.attacker_id)
            me = self.world.me
            self._last_incoming_damage_mono = time.monotonic()
            log.info(
                "[World] Hit S2C: attacker objId=0x%X → me, SC_Attack damage field=%d "
                "(HP snapshot %d/%d — often lags UserInfo/StatusUpdate; field may not match UI)",
                pkt.attacker_id,
                pkt.damage,
                me.cur_hp,
                me.max_hp,
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
        if me and pkt.target_id == me and pkt.caster_id and pkt.caster_id != me:
            self.world.register_attacker_on_me(pkt.caster_id)
            self._last_incoming_damage_mono = time.monotonic()

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

    def _on_party_spelled(self, payload: bytes) -> None:
        pkt = PartySpelled.parse(payload)
        if not pkt.effects:
            return
        self.world.on_party_spelled(pkt.object_id, pkt.effects)
        log.debug(
            "[World] PartySpelled objId=0x%X effects=%d",
            pkt.object_id,
            len(pkt.effects),
        )

    def _on_party_small_window_all(self, payload: bytes) -> None:
        pkt = PartySmallWindowAll.parse(payload)
        if pkt.declared_count == 0:
            self.world.on_party_small_window_all([])
            log.info("[World] PartySmallWindowAll: party cleared (0 members)")
            return
        if not pkt.members:
            log.debug(
                "[World] PartySmallWindowAll: skip sync (declared=%d, parsed=0 — layout mismatch?)",
                pkt.declared_count,
            )
            return
        self.world.on_party_small_window_all(pkt.members)
        log.info("[World] PartySmallWindowAll: %d member(s)", len(pkt.members))

    def _on_party_small_window_add(self, payload: bytes) -> None:
        pkt = PartySmallWindowAdd.parse(payload)
        if pkt.member and pkt.member.object_id:
            self.world.on_party_small_window_add(pkt.member)
            log.info(
                "[World] PartySmallWindowAdd: %s oid=0x%X HP %d/%d MP %d/%d",
                pkt.member.name,
                pkt.member.object_id,
                pkt.member.cur_hp,
                pkt.member.max_hp,
                pkt.member.cur_mp,
                pkt.member.max_mp,
            )

    def _on_party_small_window_delete(self, payload: bytes) -> None:
        pkt = PartySmallWindowDelete.parse(payload)
        if pkt.object_id:
            self.world.on_party_small_window_delete(pkt.object_id)
            log.info("[World] PartySmallWindowDelete: oid=0x%X", pkt.object_id)

    def _on_short_buff_status_update(self, payload: bytes) -> None:
        pkt = ShortBuffStatusUpdate.parse(payload)
        if pkt.skill_id <= 0:
            return
        self.world.on_short_buff_status_update(pkt.skill_id, pkt_object_id=pkt.object_id)
        log.debug(
            "[World] ShortBuff skillId=%d objId=0x%X",
            pkt.skill_id,
            pkt.object_id,
        )

    def set_combat_profile(self, profile: CombatProfile) -> None:
        self._combat_profile = profile
        self._rule_last_fire.clear()
        self._c2s_target_cancel_payload = normalize_target_cancel_payload(profile.target_cancel_payload)
        self._magic_skill_combat = normalize_magic_skill_payload(profile.magic_skill_payload)
        self._combat_skill_packet = normalize_buff_skill_packet(profile.combat_skill_packet)
        self._maybe_warn_combat_magic_payload_mismatch()
        if profile.move_before_targeting and not self._move_before_target_warned:
            self._move_before_target_warned = True
            log.warning(
                "[AutoCombat] move_before_targeting is set but pathing is not implemented — ignored",
            )

    def set_buff_profile(self, profile: BuffProfile) -> None:
        self._buff_profile = profile
        self._buff_last_cast.clear()
        self._buff_cast_times.clear()
        self._magic_skill_buff = normalize_magic_skill_payload(profile.magic_skill_payload)
        self._buff_skill_packet = normalize_buff_skill_packet(profile.buff_skill_packet)
        self._maybe_warn_combat_magic_payload_mismatch()
        self._log_buff_profile_loaded("apply")

    def _maybe_warn_combat_magic_payload_mismatch(self) -> None:
        """dcb vs ddd on 0x39 desyncs many Teon/L2J servers → kick on Spoil/Sweep."""
        if self._combat_skill_packet != "39":
            return
        c = self._magic_skill_combat
        b = self._magic_skill_buff
        if c == b:
            return
        log.warning(
            "[AutoCombat] Combat 0x39 body is %s but buff profile uses %s — if you disconnect on "
            "auto rules / post-kill sweep, set the same «0x39 body» on Auto combat as on Buffs, "
            "or set Combat skill packet to 2f (shortcut bar).",
            c,
            b,
        )

    def _log_buff_profile_loaded(self, reason: str) -> None:
        char = self._disk_profile_key
        p, _ = resolve_buff_profile_read_path(
            character_name=char if char is not None else None,
        )
        exists = p.is_file()
        log.info(
            "[BuffProfile] %s file=%s exists=%s buff_packet=0x%s magic_skill_payload=%s rules=%d",
            reason,
            p,
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
        if self._combat_phase == "recovering":
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
        tw = max(prof.incoming_damage_sit_block_sec, prof.aggro_retarget_window_sec)
        if self.world.any_living_attacker_threatens_me(window_sec=tw):
            log.info("[AutoCombat] Skip post-kill sit: attacker threat (recent hit / skill on you)")
            return False
        gate = prof.incoming_damage_sit_block_sec
        if gate > 0 and (time.monotonic() - self._last_incoming_damage_mono) < gate:
            log.info(
                "[AutoCombat] Skip post-kill sit: incoming damage within %.1fs",
                gate,
            )
            return False
        return True

    def _allow_idle_combat_sit(self) -> bool:
        prof = self._combat_profile
        if self.world.any_living_attacker_threatens_me(window_sec=prof.aggro_retarget_window_sec):
            return False
        if self._hostile_target_alive():
            return False
        return True

    def _combat_anchor_args(self) -> tuple[tuple[int, int, int] | None, float]:
        prof = self._combat_profile
        if not prof.combat_anchor_leash_enabled or self._combat_anchor is None:
            return (None, 0.0)
        return (self._combat_anchor, max(1.0, prof.combat_anchor_leash_radius))

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
                    flags = [self.world.abnormal_buff_active(target_oid, s) for s in match_set]
                    if any(f is True for f in flags):
                        buff_present = True
                    elif match_set and all(f is False for f in flags):
                        buff_present = False
                    else:
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

    async def _maybe_combat_rules(
        self,
        mob: Optional[Npc],
        *,
        opening_only: bool = False,
    ) -> None:
        prof = self._combat_profile
        if not prof.rules:
            return
        me = self.world.me
        in_combat = mob is not None
        now = time.monotonic()
        for idx, rule in enumerate(prof.rules):
            if opening_only and not rule.fire_before_first_attack:
                continue
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
                sid = rule.rebuff_missing_skill_id
                oid = self.world.me.object_id
                st = self.world.abnormal_buff_active(oid, sid) if oid else None
                if st is True:
                    continue
                if st is None and sid in self.world.abnormal_buff_skill_ids:
                    continue
            if mob is not None:
                teff = self.world.abnormal_skill_ids_for_object(mob.object_id)
                if rule.require_target_missing_abnormal_ids:
                    miss = set(rule.require_target_missing_abnormal_ids)
                    if miss & teff:
                        continue
                if rule.require_target_has_abnormal_ids:
                    need = set(rule.require_target_has_abnormal_ids)
                    if not (need & teff):
                        continue
            elif rule.require_target_missing_abnormal_ids or rule.require_target_has_abnormal_ids:
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
                gap = max(0.0, prof.combat_skill_min_interval_sec)
                if gap > 0:
                    last_s = self._combat_skill_last_cast.get(rule.skill_id, 0.0)
                    if now - last_s < gap:
                        continue
                self.use_skill(rule.skill_id)
                self._combat_skill_last_cast[rule.skill_id] = now
                self._rule_last_fire[idx] = now
                log.info(
                    "[AutoCombat] Rule #%d skillId=%d%s",
                    idx,
                    rule.skill_id,
                    " (opening)" if opening_only else "",
                )
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
                log.info(
                    "[AutoCombat] Rule #%d useItem objId=0x%X template=%d%s",
                    idx,
                    oid,
                    rule.item_id,
                    " (opening)" if opening_only else "",
                )
                await asyncio.sleep(prof.post_skill_delay)
                return

    async def _ensure_standing_before_combat(self) -> None:
        """After post-kill / idle sit regen, stand before targeting (attack while sitting fails)."""
        me = self.world.me
        if me.me_sitting is not True:
            return
        log.info("[AutoCombat] Standing before engage (still sitting)")
        await self._ensure_standing_after_recovery()
        await asyncio.sleep(
            max(0.08, min(0.6, self._combat_profile.post_kill_recovery_after_stand_sec))
        )

    # ------------------------------------------------------------------ #
    # Auto-combat
    # ------------------------------------------------------------------ #

    def start_auto_combat(self, combat_range: float = 2000.0) -> None:
        """Start auto-combat loop. Must be called from the asyncio loop thread."""
        if self._auto_combat:
            self.stop_auto_combat()
        self._auto_combat = True
        self._combat_range = combat_range
        me = self.world.me
        self._combat_anchor = (me.x, me.y, me.z) if me.object_id else None
        self._no_mob_anchor_since = None
        self._auto_task = asyncio.ensure_future(self._auto_combat_loop())
        log.info("[BotEngine] Auto-combat started (range=%.0f)", combat_range)

    def stop_auto_combat(self) -> None:
        """Stop auto-combat loop."""
        self._auto_combat = False
        self._combat_phase = "idle"
        self._auto_combat_last_target_oid = 0
        self._combat_anchor = None
        self._no_mob_anchor_since = None
        if self._auto_task and not self._auto_task.done():
            self._auto_task.cancel()
        self._auto_task = None
        log.info("[BotEngine] Auto-combat stopped")

    def get_combat_diagnostics(self) -> dict[str, object]:
        """Safe snapshot for UI (main thread); no asyncio wait."""
        tid = self.world.me.target_id
        n = self.world.npcs.get(tid) if tid else None
        target_lbl = ""
        if n and n.is_attackable:
            target_lbl = (
                f"npcId={n.npc_id} oid=0x{tid:X} d={self.world.dist_to(n):.0f}"
            )
        elif tid:
            target_lbl = f"oid=0x{tid:X}"
        me = self.world.me
        sit = me.me_sitting
        sit_s = "?" if sit is None else ("sit" if sit else "stand")
        return {
            "phase": self._combat_phase,
            "auto_combat": self._auto_combat,
            "target": target_lbl,
            "sitting": sit_s,
            "cur_cp": me.cur_cp,
            "max_cp": me.max_cp,
            "buff_rules": len(self._buff_profile.rules) if self._buff_profile else 0,
            "combat_rules": len(self._combat_profile.rules),
            "anchor": self._combat_anchor,
        }

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
                    if (
                        prof.loot_respect_anchor_leash
                        and prof.combat_anchor_leash_enabled
                        and self._combat_anchor is not None
                    ):
                        ax, ay, az = self._combat_anchor
                        lr = max(1.0, prof.combat_anchor_leash_radius)
                        items_around = [
                            it for it in items_around
                            if World.dist_xyz(ax, ay, az, it.x, it.y, it.z) <= lr
                        ]
                    if items_around:
                        looted = await self.loot_nearby_async(
                            prof.loot_range,
                            max_attempts=56,
                            delay_sec=max(0.05, prof.idle_loot_item_delay_sec),
                            empty_polls_to_stop=5,
                        )
                        log.info("[AutoCombat] Loot: %d pickup attempts", looted)
                        if looted:
                            await asyncio.sleep(max(0.05, prof.open_combat_pre_loot_sleep_sec))

                never = frozenset(prof.never_attack_object_ids) | frozenset(
                    prof.party_protect_object_ids
                )
                wl = frozenset(prof.npc_whitelist_ids)
                bl = frozenset(prof.npc_blacklist_ids)
                anchor_xyz, anchor_r = self._combat_anchor_args()
                mob = self.world.pick_auto_combat_target(
                    self._combat_range,
                    prefer_aggro=prof.prefer_aggro_mobs,
                    retain_target_oid=self._auto_combat_last_target_oid,
                    retain_max_dist=max(0.0, prof.retain_current_target_max_dist),
                    npc_blacklist=bl,
                    attack_only_whitelist=prof.attack_only_whitelist_mobs,
                    npc_whitelist=wl,
                    target_z_range_max=max(0.0, prof.target_z_range_max),
                    skip_summoned=prof.skip_summoned_npcs,
                    never_attack_oids=never,
                    anchor_xyz=anchor_xyz,
                    anchor_leash_radius=anchor_r,
                )
                if mob:
                    self._no_mob_anchor_since = None
                    # Always resolve by objectId — NpcInfo replaces dict entries, stale mob refs never update.
                    target_oid = mob.object_id
                    self._auto_combat_last_target_oid = target_oid
                    log.info("[AutoCombat] Target: npcId=%d '%s' objId=0x%X dist=%.0f hp=%.0f%%",
                             mob.npc_id, mob.name or mob.title or '?',
                             target_oid, self.world.dist_to(mob), mob.hp_pct)
                    await self._ensure_standing_before_combat()
                    if not self._auto_combat:
                        return
                    # Step 1: Target the mob via Action (0x04)
                    self.attack(target_oid)
                    await asyncio.sleep(self._combat_profile.post_target_delay)
                    if not self._auto_combat:
                        return
                    wm = self.world.npcs.get(target_oid)
                    await self._maybe_combat_rules(wm, opening_only=True)
                    if not self._auto_combat:
                        return
                    await self._maybe_combat_rules(wm, opening_only=False)
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
                    last_rules_tick = t0
                    rules_iv = max(0.0, prof.combat_rules_tick_sec)
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
                                self._auto_combat_last_target_oid = 0
                                break
                            now = time.monotonic()
                            if prof.retarget_to_aggro_enabled and not self.world.is_npc_attacking_me(
                                target_oid, window_sec=prof.aggro_retarget_window_sec
                            ):
                                alt = self.world.nearest_aggro_npc_except(
                                    target_oid,
                                    self._combat_range,
                                    target_z_range_max=max(0.0, prof.target_z_range_max),
                                    npc_blacklist=bl,
                                    attack_only_whitelist=prof.attack_only_whitelist_mobs,
                                    npc_whitelist=wl,
                                    skip_summoned=prof.skip_summoned_npcs,
                                    never_attack_oids=never,
                                    aggro_window_sec=prof.aggro_retarget_window_sec,
                                    anchor_xyz=anchor_xyz,
                                    anchor_leash_radius=anchor_r,
                                )
                                if alt is not None:
                                    log.info(
                                        "[AutoCombat] Retarget to aggro npc objId=0x%X (was 0x%X)",
                                        alt.object_id,
                                        target_oid,
                                    )
                                    target_oid = alt.object_id
                                    self._auto_combat_last_target_oid = target_oid
                                    t0 = time.monotonic()
                                    self.attack(target_oid)
                                    await asyncio.sleep(reattack_sleep)
                                    wn = self.world.npcs.get(target_oid)
                                    await self._maybe_combat_rules(wn, opening_only=True)
                                    await self._maybe_combat_rules(wn, opening_only=False)
                                    self.force_attack()
                                    last_reattack = time.monotonic()
                                    last_rules_tick = time.monotonic()
                            if rules_iv > 0 and (now - last_rules_tick) >= rules_iv:
                                await self._maybe_combat_rules(self.world.npcs.get(target_oid))
                                last_rules_tick = time.monotonic()
                            if now - last_reattack >= reattack_sec:
                                if not self._npc_fightable(target_oid):
                                    log.info("[AutoCombat] Target no longer fightable — stop re-attacking")
                                    self._auto_combat_last_target_oid = 0
                                    break
                                self.attack(target_oid)
                                await asyncio.sleep(reattack_sleep)
                                await self._maybe_combat_rules(self.world.npcs.get(target_oid))
                                self.force_attack()
                                last_reattack = time.monotonic()
                            await asyncio.sleep(kill_tick)
                    finally:
                        self._combat_phase = "idle"
                    if (
                        prof.post_kill_sweep_enabled
                        and prof.post_kill_sweep_skill_id > 0
                        and self.world.is_skill_ready(prof.post_kill_sweep_skill_id)
                    ):
                        self.target_object(target_oid)
                        await asyncio.sleep(max(0.05, prof.post_kill_sweep_delay_sec))
                        self.use_skill(prof.post_kill_sweep_skill_id)
                        await asyncio.sleep(max(0.05, prof.post_skill_delay))
                    # Drop target so we do not stay glued to a corpse if HP/death packets lag.
                    self.cancel_target()
                    # Auto-loot after kill — wait for drop packets, then pick up
                    if prof.auto_loot:
                        await asyncio.sleep(max(0.05, prof.post_kill_spawn_wait_sec))
                        looted = await self.loot_nearby_async(
                            prof.loot_range,
                            max_attempts=80,
                            delay_sec=max(0.05, prof.post_kill_loot_item_delay_sec),
                            empty_polls_to_stop=6,
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
                            max_attempts=48,
                            delay_sec=max(0.05, prof.idle_loot_item_delay_sec),
                            empty_polls_to_stop=5,
                        )
                        if looted:
                            log.info("[AutoCombat] Idle loot: %d pickup attempts", looted)
                    total = len(self.world.npcs)
                    atk = sum(1 for n in self.world.npcs.values()
                              if n.is_attackable and not n.is_dead)
                    log.info("[AutoCombat] No mobs in range (world_npcs=%d, attackable=%d, range=%.0f)",
                             total, atk, self._combat_range)
                    self._auto_combat_last_target_oid = 0
                    me = self.world.me
                    if prof.combat_anchor_reset_idle_sec > 0 and me.object_id:
                        nma = time.monotonic()
                        if self._no_mob_anchor_since is None:
                            self._no_mob_anchor_since = nma
                        elif (nma - self._no_mob_anchor_since) >= prof.combat_anchor_reset_idle_sec:
                            self._combat_anchor = (me.x, me.y, me.z)
                            self._no_mob_anchor_since = nma
                            log.info(
                                "[AutoCombat] Combat anchor recentered after %.0fs idle",
                                prof.combat_anchor_reset_idle_sec,
                            )
                    if prof.combat_sit_while_idle_enabled and self._allow_idle_combat_sit():
                        me = self.world.me
                        if me.effective_max_hp() > 0 and me.hp_pct_safe < prof.combat_sit_hp_below_pct:
                            self._combat_phase = "recovering"
                            self._recovery_sent_sit_toggle = False
                            try:
                                await self._ensure_sitting_for_recovery()
                                try:
                                    await self._wait_recovery(prof.combat_stand_hp_pct)
                                finally:
                                    await self._ensure_standing_after_recovery()
                            finally:
                                self._recovery_sent_sit_toggle = False
                                self._combat_phase = "idle"
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
        """Use a skill by ID. Combat: 0x39 or 0x2F (Teon bar). Buff: BuffProfile buff_skill_packet."""
        use_2f = (for_buff and self._buff_skill_packet == "2f") or (
            not for_buff and self._combat_skill_packet == "2f"
        )
        if use_2f:
            opcode, payload = cs.build_shortcut_skill_use(skill_id, ctrl, shift)
            self.game_proxy.inject_to_server(opcode, payload)
            log.info(
                "[Bot] UseSkill → skillId=%d 0x2F len=%d hex=%s (%s)",
                skill_id,
                len(payload),
                payload.hex(),
                "buff" if for_buff else "combat",
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
        """Undo sit after regen: one or more RequestActionUse(0) toggles until server says standing.

        MoveToPoint sync can clear me_sitting falsely; ChangeWaitType can lag — retries help."""
        me = self.world.me
        if not (me.me_sitting is True or self._recovery_sent_sit_toggle):
            return
        prof = self._combat_profile
        attempts = max(1, min(4, int(prof.recovery_stand_toggle_attempts)))
        for i in range(attempts):
            if not self._auto_combat:
                break
            self.sit_stand()
            await asyncio.sleep(_RECOVERY_TOGGLE_ACK_SEC)
            me = self.world.me
            # Only stop when server reports standing; None = unknown — keep toggling (was: «not True» exited too early).
            if me.me_sitting is False:
                return
        log.warning(
            "[AutoCombat] Still sitting after %d stand toggle(s) — try flipping "
            "recovery_change_wait_type_sit_raw (0↔1) in autocombat.json; see docs/recovery-sit-stand.md",
            attempts,
        )

    def pickup(self, item_object_id: int, *, quiet: bool = False) -> None:
        """Pick up item on ground by right-clicking it (CS_Action 0x04).
        This is how the real client picks up items — NOT via 0x48."""
        sess = self.game_proxy.session
        if not sess.crypto_initialized or not sess.xor_c2s_server:
            return
        me = self.world.me
        opcode, payload = cs.build_action(item_object_id, me.x, me.y, me.z)
        self.game_proxy.inject_to_server(opcode, payload)
        if quiet:
            log.debug(
                "[Bot] Pickup (Action) → objectId=0x%X from=(%d,%d,%d)",
                item_object_id,
                me.x,
                me.y,
                me.z,
            )
        else:
            log.info(
                "[Bot] Pickup (Action) → objectId=0x%X from=(%d,%d,%d)",
                item_object_id,
                me.x,
                me.y,
                me.z,
            )

    async def loot_nearby_async(
        self,
        max_dist: float = 800.0,
        *,
        max_attempts: int = 64,
        delay_sec: float = 0.28,
        empty_polls_to_stop: int = 4,
        max_pickup_tries_per_object: int = 4,
    ) -> int:
        """Pick up ground items via CS_Action. One closest item per iteration; stale oids dropped."""
        picked = 0
        cap = max(1, max_attempts)
        pause = max(0.05, delay_sec)
        empty = 0
        max_empty = max(2, empty_polls_to_stop)
        per_oid_tries: dict[int, int] = {}
        max_oid = max(1, max_pickup_tries_per_object)
        while picked < cap:
            sess = self.game_proxy.session
            if not sess.crypto_initialized:
                log.info("[AutoCombat] Loot stopped — game session disconnected")
                break
            items = self.world.get_items_in_range(max_dist)
            prof = self._combat_profile
            if (
                prof.loot_respect_anchor_leash
                and prof.combat_anchor_leash_enabled
                and self._combat_anchor is not None
            ):
                ax, ay, az = self._combat_anchor
                lr = max(1.0, prof.combat_anchor_leash_radius)
                items = [
                    it for it in items
                    if World.dist_xyz(ax, ay, az, it.x, it.y, it.z) <= lr
                ]
            if not items:
                empty += 1
                if empty >= max_empty:
                    break
                await asyncio.sleep(0.12)
                continue
            empty = 0
            item = items[0]
            oid = item.object_id
            tries = per_oid_tries.get(oid, 0)
            if tries >= max_oid:
                self.world.ground_items.pop(oid, None)
                per_oid_tries.pop(oid, None)
                log.warning(
                    "[AutoCombat] Removed stale ground item objId=0x%X after %d pickup tries",
                    oid,
                    max_oid,
                )
                continue
            self.pickup(oid, quiet=True)
            picked += 1
            per_oid_tries[oid] = tries + 1
            await asyncio.sleep(pause)
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
            prof = self._combat_profile
            if self.world.any_living_attacker_threatens_me(
                window_sec=max(prof.incoming_damage_sit_block_sec, prof.aggro_retarget_window_sec)
            ):
                log.info("[AutoCombat] Recovery interrupted — under attack")
                return
            me = self.world.me
            hp_ok = me.hp_recovery_reached(target_hp_pct)
            mp_ok = (
                not mp_gate
                or me.effective_max_mp() <= 0
                or me.mp_pct_safe >= prof.recovery_stand_mp_pct
            )
            if hp_ok and mp_ok:
                log.info(
                    "[AutoCombat] Recovery done — HP=%.0f%% (cur=%d baseline_max=%d) MP=%.0f%% — resuming",
                    me.hp_pct_safe,
                    me.cur_hp,
                    me.max_hp_baseline,
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
