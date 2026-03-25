"""
World state — tracks everything visible in the game world.

Updated by BotEngine as packets arrive from the server.
"""
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from engine.combat_profile import DEFAULT_TARGET_Z_RANGE_MAX

log = logging.getLogger(__name__)

# Throttle "rejected bogus max HP/MP" warnings (seconds).
_ME_HP_SANITY_WARN_INTERVAL_SEC = 5.0
# Reject StatusUpdate max if below this fraction of UserInfo baseline (wrong attr id).
_ME_MAX_FRAC_OF_BASELINE = 0.10
# Reject ATTR_MAX_* absurdly above UserInfo baseline (wrong attr often yields huge values).
# Buffs can raise max several times over baseline; 25× stays below typical coordinate garbage.
_ME_MAX_SANITY_MULTIPLIER = 25.0
# Never treat pool sizes above this as real (coordinates / garbage in wrong slot).
_ME_ABSOLUTE_MAX_POOL = 2_000_000
# MoveToPoint with smaller delta is treated as sync, not «started walking» — do not clear sitting.
_ME_MOVE_CLEARS_SITTING_MIN_DELTA = 64

from core.packets.server import (
    UserInfo,
    NpcInfo,
    DeleteObject,
    StatusUpdate,
    MoveToPoint,
    Die,
    SpawnItem,
    ItemList,
    InventoryUpdate,
    MagicSkillLaunched,
    PartyMemberInfo,
    ATTR_CUR_HP,
    ATTR_MAX_HP,
    ATTR_CUR_MP,
    ATTR_MAX_MP,
    ATTR_CUR_CP,
    ATTR_MAX_CP,
)


@dataclass
class MyChar:
    object_id: int = 0
    x: int = 0
    y: int = 0
    z: int = 0
    heading: int = 0
    name: str = ""
    title: str = ""
    level: int = 0
    cur_hp: int = 0
    max_hp: int = 1
    cur_mp: int = 0
    max_mp: int = 1
    target_id: int = 0
    # Last trustworthy max from UserInfo (StatusUpdate max can be wrong attr on some shards).
    max_hp_baseline: int = 0
    max_mp_baseline: int = 0
    # None = unknown until SC_ChangeWaitType / move; drives recovery sit/stand (toggle is ambiguous alone).
    me_sitting: Optional[bool] = None
    cur_cp: int = 0
    max_cp: int = 0

    def _sanitized_max_pool(self, mx: int, baseline: int, cur: int) -> int:
        """Return mx if plausible for HP/MP % math, else 0 (fall back to baseline/cur)."""
        if mx <= 0 or mx > _ME_ABSOLUTE_MAX_POOL:
            return 0
        if baseline > 0 and mx > int(baseline * _ME_MAX_SANITY_MULTIPLIER):
            return 0
        if baseline > 0 and cur > 0 and mx > max(cur * 100, baseline * 3):
            # e.g. cur=176, garbage max=50000
            return 0
        return mx

    def effective_max_hp(self) -> int:
        """Denominator for HP%; ignores Status max that is tiny vs UserInfo baseline (wrong attr)."""
        c = self.cur_hp
        mx = self._sanitized_max_pool(self.max_hp, self.max_hp_baseline, c)
        b = self.max_hp_baseline
        if mx > 0 and mx >= c:
            if b == 0 or mx >= max(1, int(b * _ME_MAX_FRAC_OF_BASELINE)):
                return mx
        if b > 0 and b >= c:
            return max(b, c)
        return max(mx, b, c, 1)

    def effective_max_mp(self) -> int:
        c = self.cur_mp
        mx = self._sanitized_max_pool(self.max_mp, self.max_mp_baseline, c)
        b = self.max_mp_baseline
        if mx > 0 and mx >= c:
            if b == 0 or mx >= max(1, int(b * _ME_MAX_FRAC_OF_BASELINE)):
                return mx
        if b > 0 and b >= c:
            return max(b, c)
        return max(mx, b, c, 1)

    @property
    def hp_pct(self) -> float:
        m = self.effective_max_hp()
        return (self.cur_hp / m * 100) if m else 0.0

    @property
    def mp_pct(self) -> float:
        m = self.effective_max_mp()
        return (self.cur_mp / m * 100) if m else 0.0

    @property
    def hp_pct_safe(self) -> float:
        m = self.effective_max_hp()
        return max(0.0, min(100.0, self.cur_hp / m * 100))

    def hp_recovery_reached(self, target_hp_pct: float) -> bool:
        """Post-kill sit regen: HP%% target, plus cur vs UserInfo baseline when StatusUpdate MAX skews %%."""
        if target_hp_pct <= 0:
            return True
        if self.hp_pct_safe >= target_hp_pct:
            return True
        b = self.max_hp_baseline
        c = self.cur_hp
        if b > 0 and c >= max(1, b - 1):
            return True
        if b > 0 and c >= int(b * target_hp_pct / 100.0):
            return True
        return False

    @property
    def mp_pct_safe(self) -> float:
        m = self.effective_max_mp()
        return max(0.0, min(100.0, self.cur_mp / m * 100))


@dataclass
class Npc:
    object_id: int
    npc_type_id: int
    name: str
    title: str
    x: int
    y: int
    z: int
    heading: int
    is_attackable: bool
    hp_pct: float = 100.0
    is_dead: bool = False
    cur_hp: int = 0
    max_hp: int = 0
    # True only after ATTR_CUR_HP in StatusUpdate; avoids false "dead" when server sends MAX_HP alone
    # while cur_hp is still the default 0.
    cur_hp_known: bool = False
    is_summoned: bool = False

    @property
    def npc_id(self) -> int:
        return self.npc_type_id - 1_000_000

    def looks_eliminated(self) -> bool:
        """True if mob should be treated as dead for targeting / kill detection.
        Uses is_dead, dead_ids (via callers), and absolute HP from StatusUpdate — not NpcInfo hp_pct,
        which is often 0 or misread and would hide every mob if used as a death signal."""
        if self.is_dead:
            return True
        if self.cur_hp_known and self.max_hp > 0 and self.cur_hp <= 0:
            return True
        return False


@dataclass
class GroundItem:
    object_id: int
    item_id: int
    count: int
    x: int
    y: int
    z: int


class World:
    def __init__(self):
        self.me = MyChar()
        self.npcs: dict[int, Npc] = {}       # objectId → Npc
        self.dead_ids: set[int] = set()       # objectIds of dead units
        self.ground_items: dict[int, GroundItem] = {}  # objectId → GroundItem
        self._dead_timestamps: dict[int, float] = {}   # objectId → time of death
        # From SC_SkillList (ids only — no names in classic Interlude packet)
        self.my_skills: dict[int, int] = {}
        # Skill ids that appeared in at least one SkillList this session (detect «removed from list»)
        self.skill_ids_seen_in_skill_list: set[int] = set()
        # From SkillList — passive skills cannot be cast via RequestMagicSkillUse
        self.passive_skill_ids: set[int] = set()
        # SC_ItemList: object_id → (template itemId, count)
        self.inventory_by_object: dict[int, tuple[int, int]] = {}
        # SC_SkillCoolTime: skill_id → monotonic time when reuse expired
        self.skill_reuse_ready_at: dict[int, float] = {}
        # SC_AbnormalStatusUpdate: active buff / effect skill ids (for rebuff rules) — self only
        self.abnormal_buff_skill_ids: set[int] = set()
        # Same data keyed by objectId (self, party target, etc.) for buff maintenance
        self.abnormal_buffs_by_object: dict[int, set[int]] = {}
        # SC_MagicSkillLaunched (self as caster): last skill_level per skill id (toggle auras / Teon)
        self.cast_notify_skill_level: dict[int, int] = {}
        self._last_me_hp_sanity_warn: float = 0.0
        # Last time this object id dealt damage to self (SC_Attack target == me)
        self._attackers_on_me: dict[int, float] = {}
        # Monotonic expiry for abnormal effects (seconds); complements skill id sets
        self._abnormal_expire_at: dict[int, dict[int, float]] = {}
        # PartySmallWindow* + StatusUpdate / PartySpelled for members (objectId → row)
        self.party_members: dict[int, PartyMemberInfo] = {}

    # ------------------------------------------------------------------ #
    # Packet handlers (called by BotEngine)
    # ------------------------------------------------------------------ #

    def on_party_small_window_all(self, members: list[PartyMemberInfo]) -> None:
        """Replace party roster from SC_PartySmallWindowAll (count 0 = leave party)."""
        self.party_members.clear()
        for m in members:
            if m.object_id:
                self.party_members[m.object_id] = m

    def on_party_small_window_add(self, m: PartyMemberInfo) -> None:
        if m.object_id:
            self.party_members[m.object_id] = m

    def on_party_small_window_delete(self, object_id: int) -> None:
        if object_id:
            self.party_members.pop(object_id, None)

    def on_party_small_window_update(self, pkt: object) -> None:
        """Update HP/MP/CP for one party member from SC_PartySmallWindowUpdate."""
        oid = getattr(pkt, "object_id", 0)
        if not oid or oid not in self.party_members:
            return
        m = self.party_members[oid]
        m.cur_hp = getattr(pkt, "cur_hp", m.cur_hp)
        m.max_hp = getattr(pkt, "max_hp", m.max_hp)
        m.cur_mp = getattr(pkt, "cur_mp", m.cur_mp)
        m.max_mp = getattr(pkt, "max_mp", m.max_mp)
        m.cur_cp = getattr(pkt, "cur_cp", m.cur_cp)
        m.max_cp = getattr(pkt, "max_cp", m.max_cp)

    def on_change_wait_type(self, object_id: int, wait_type_raw: int, *, sit_raw: int = 0) -> None:
        """Update local sit state from SC_ChangeWaitType (self only)."""
        if object_id != self.me.object_id or not object_id:
            return
        sitting: Optional[bool] = None
        if wait_type_raw in (0, 1):
            sitting = wait_type_raw == sit_raw
        elif wait_type_raw in (5, 7):
            sitting = True
        elif wait_type_raw in (2, 3, 4, 6):
            sitting = False
        if sitting is None:
            log.debug(
                "[World] ChangeWaitType self: unmapped wait_type=%d — me_sitting unchanged; "
                "if sit/stand is wrong set recovery_change_wait_type_sit_raw (0 or 1) in autocombat.json",
                wait_type_raw,
            )
            return
        self.me.me_sitting = sitting

    def on_user_info(self, pkt: UserInfo) -> None:
        me = self.me
        prev_oid = me.object_id
        me.object_id = pkt.object_id
        if pkt.object_id and pkt.object_id != prev_oid:
            me.me_sitting = False
        me.x = pkt.x
        me.y = pkt.y
        me.z = pkt.z
        me.name = pkt.name
        me.title = pkt.title
        me.level = pkt.level
        me.cur_hp = pkt.cur_hp
        me.max_hp = pkt.max_hp
        me.cur_mp = pkt.cur_mp
        me.max_mp = pkt.max_mp
        if pkt.max_hp > 0:
            me.max_hp_baseline = pkt.max_hp
        if pkt.max_mp > 0:
            me.max_mp_baseline = pkt.max_mp

    def _warn_me_hp_sanity(self, msg: str, *args: object) -> None:
        now = time.monotonic()
        if now - self._last_me_hp_sanity_warn < _ME_HP_SANITY_WARN_INTERVAL_SEC:
            return
        self._last_me_hp_sanity_warn = now
        log.warning(msg, *args)

    def _accept_me_max_hp(self, cur_hp: int, cand_max: int) -> bool:
        if cand_max <= 0:
            return False
        if cand_max < cur_hp:
            self._warn_me_hp_sanity(
                "[World] Reject bogus ATTR_MAX_HP for self: max=%d < cur_hp=%d (keep last max / baseline)",
                cand_max,
                cur_hp,
            )
            return False
        b = self.me.max_hp_baseline
        if b > 0 and cand_max < max(1, int(b * _ME_MAX_FRAC_OF_BASELINE)):
            self._warn_me_hp_sanity(
                "[World] Reject bogus ATTR_MAX_HP for self: max=%d << baseline=%d",
                cand_max,
                b,
            )
            return False
        if cand_max > _ME_ABSOLUTE_MAX_POOL:
            self._warn_me_hp_sanity(
                "[World] Reject ATTR_MAX_HP for self: max=%d (absurd absolute)",
                cand_max,
            )
            return False
        if b > 0 and cand_max > int(b * _ME_MAX_SANITY_MULTIPLIER):
            self._warn_me_hp_sanity(
                "[World] Reject ATTR_MAX_HP for self: max=%d >> baseline=%d (wrong attr?)",
                cand_max,
                b,
            )
            return False
        if b > 0 and cur_hp > 0 and cand_max > max(cur_hp * 100, b * 3):
            self._warn_me_hp_sanity(
                "[World] Reject ATTR_MAX_HP for self: max=%d vs cur=%d baseline=%d",
                cand_max,
                cur_hp,
                b,
            )
            return False
        return True

    def _accept_me_max_mp(self, cur_mp: int, cand_max: int) -> bool:
        if cand_max <= 0:
            return False
        if cand_max < cur_mp:
            self._warn_me_hp_sanity(
                "[World] Reject bogus ATTR_MAX_MP for self: max=%d < cur_mp=%d",
                cand_max,
                cur_mp,
            )
            return False
        b = self.me.max_mp_baseline
        if b > 0 and cand_max < max(1, int(b * _ME_MAX_FRAC_OF_BASELINE)):
            self._warn_me_hp_sanity(
                "[World] Reject bogus ATTR_MAX_MP for self: max=%d << baseline=%d",
                cand_max,
                b,
            )
            return False
        if cand_max > _ME_ABSOLUTE_MAX_POOL:
            self._warn_me_hp_sanity(
                "[World] Reject ATTR_MAX_MP for self: max=%d (absurd absolute)",
                cand_max,
            )
            return False
        if b > 0 and cand_max > int(b * _ME_MAX_SANITY_MULTIPLIER):
            self._warn_me_hp_sanity(
                "[World] Reject ATTR_MAX_MP for self: max=%d >> baseline=%d (wrong attr?)",
                cand_max,
                b,
            )
            return False
        if b > 0 and cur_mp > 0 and cand_max > max(cur_mp * 100, b * 3):
            self._warn_me_hp_sanity(
                "[World] Reject ATTR_MAX_MP for self: max=%d vs cur=%d baseline=%d",
                cand_max,
                cur_mp,
                b,
            )
            return False
        return True

    def on_npc_info(self, pkt: NpcInfo) -> None:
        # If the server says alive (isDead=0), always drop stale local kill bookkeeping.
        # Otherwise `dead_ids` from a bad Die/StatusUpdate never clears: is_dead stays true forever
        # because we used `pkt.is_dead or oid in dead_ids` and never entered `if not is_dead`.
        if not pkt.is_dead:
            self.dead_ids.discard(pkt.object_id)
            self._dead_timestamps.pop(pkt.object_id, None)
        is_dead = bool(pkt.is_dead) or (pkt.object_id in self.dead_ids)
        prev = self.npcs.get(pkt.object_id)
        self.npcs[pkt.object_id] = Npc(
            object_id=pkt.object_id,
            npc_type_id=pkt.npc_type_id,
            name=pkt.name,
            title=pkt.title,
            x=pkt.x, y=pkt.y, z=pkt.z,
            heading=pkt.heading,
            is_attackable=pkt.is_attackable,
            hp_pct=pkt.hp_pct,
            is_dead=is_dead,
            cur_hp=prev.cur_hp if prev else 0,
            max_hp=prev.max_hp if prev else 0,
            cur_hp_known=prev.cur_hp_known if prev else False,
            is_summoned=pkt.is_summoned,
        )

    def on_delete_object(self, pkt: DeleteObject) -> None:
        self.npcs.pop(pkt.object_id, None)
        self.dead_ids.discard(pkt.object_id)
        self._dead_timestamps.pop(pkt.object_id, None)
        self.ground_items.pop(pkt.object_id, None)
        self.inventory_by_object.pop(pkt.object_id, None)

    def on_spawn_item(self, pkt: SpawnItem) -> None:
        self.ground_items[pkt.object_id] = GroundItem(
            object_id=pkt.object_id,
            item_id=pkt.item_id,
            count=pkt.count,
            x=pkt.x, y=pkt.y, z=pkt.z,
        )
        # Drop from a mob usually means that object is dead; Teon often sends this before/without
        # a clean Die packet, so auto-combat can leave the kill loop immediately.
        d = pkt.dropper_id
        if d and d in self.npcs:
            npc = self.npcs[d]
            if npc.is_attackable and not npc.is_dead:
                npc.is_dead = True
                self.dead_ids.add(d)
                self._dead_timestamps[d] = time.monotonic()

    def on_status_update(self, pkt: StatusUpdate) -> None:
        if pkt.object_id == self.me.object_id:
            if ATTR_CUR_HP in pkt.attrs:
                self.me.cur_hp = pkt.attrs[ATTR_CUR_HP]
            if ATTR_MAX_HP in pkt.attrs:
                cand = pkt.attrs[ATTR_MAX_HP]
                if self._accept_me_max_hp(self.me.cur_hp, cand):
                    self.me.max_hp = cand
            if ATTR_CUR_MP in pkt.attrs:
                self.me.cur_mp = pkt.attrs[ATTR_CUR_MP]
            if ATTR_MAX_MP in pkt.attrs:
                cand = pkt.attrs[ATTR_MAX_MP]
                if self._accept_me_max_mp(self.me.cur_mp, cand):
                    self.me.max_mp = cand
            if ATTR_CUR_CP in pkt.attrs:
                self.me.cur_cp = pkt.attrs[ATTR_CUR_CP]
            if ATTR_MAX_CP in pkt.attrs:
                v = pkt.attrs[ATTR_MAX_CP]
                if v > 0:
                    self.me.max_cp = v
        elif pkt.object_id in self.npcs:
            npc = self.npcs[pkt.object_id]
            if ATTR_MAX_HP in pkt.attrs:
                npc.max_hp = pkt.attrs[ATTR_MAX_HP]
            saw_cur_hp = ATTR_CUR_HP in pkt.attrs
            if saw_cur_hp:
                npc.cur_hp = pkt.attrs[ATTR_CUR_HP]
                npc.cur_hp_known = True
            if saw_cur_hp and npc.max_hp > 0:
                npc.hp_pct = npc.cur_hp / npc.max_hp * 100
            if saw_cur_hp and npc.max_hp > 0 and npc.cur_hp <= 0:
                npc.is_dead = True
                self.dead_ids.add(pkt.object_id)
            elif saw_cur_hp and npc.max_hp > 0 and npc.cur_hp > 0 and npc.is_dead:
                # HP came back (revive / respawn packet) — allow targeting again.
                npc.is_dead = False
                self.dead_ids.discard(pkt.object_id)
                self._dead_timestamps.pop(pkt.object_id, None)
            elif saw_cur_hp and npc.max_hp > 0 and npc.cur_hp > 0:
                # Alive with HP — do not keep stale death cooldown from bad drop/Die packets.
                self._dead_timestamps.pop(pkt.object_id, None)
        elif pkt.object_id in self.party_members:
            pm = self.party_members[pkt.object_id]
            if ATTR_CUR_HP in pkt.attrs:
                pm.cur_hp = pkt.attrs[ATTR_CUR_HP]
            if ATTR_MAX_HP in pkt.attrs:
                v = pkt.attrs[ATTR_MAX_HP]
                if v > 0:
                    pm.max_hp = v
            if ATTR_CUR_MP in pkt.attrs:
                pm.cur_mp = pkt.attrs[ATTR_CUR_MP]
            if ATTR_MAX_MP in pkt.attrs:
                v = pkt.attrs[ATTR_MAX_MP]
                if v > 0:
                    pm.max_mp = v
            if ATTR_CUR_CP in pkt.attrs:
                pm.cur_cp = pkt.attrs[ATTR_CUR_CP]
            if ATTR_MAX_CP in pkt.attrs:
                v = pkt.attrs[ATTR_MAX_CP]
                if v > 0:
                    pm.max_cp = v

    def on_move(self, pkt: MoveToPoint) -> None:
        if pkt.object_id == self.me.object_id:
            self.me.x = pkt.orig_x
            self.me.y = pkt.orig_y
            if pkt.has_orig_z:
                self.me.z = pkt.orig_z
            # Large delta ⇒ real path / teleport; tiny delta ⇒ position sync while sitting — keep sit flag.
            dz = abs(pkt.dest_z - pkt.orig_z) if pkt.has_orig_z else 0
            if (
                abs(pkt.dest_x - pkt.orig_x) >= _ME_MOVE_CLEARS_SITTING_MIN_DELTA
                or abs(pkt.dest_y - pkt.orig_y) >= _ME_MOVE_CLEARS_SITTING_MIN_DELTA
                or dz >= _ME_MOVE_CLEARS_SITTING_MIN_DELTA
            ):
                self.me.me_sitting = False
        elif pkt.object_id in self.npcs:
            npc = self.npcs[pkt.object_id]
            npc.x = pkt.orig_x
            npc.y = pkt.orig_y
            if pkt.has_orig_z:
                npc.z = pkt.orig_z
            # Corpses rarely move; a move implies the unit is still active — clear stale «dead» flags.
            if npc.is_dead:
                npc.is_dead = False
                self.dead_ids.discard(pkt.object_id)
                self._dead_timestamps.pop(pkt.object_id, None)

    def on_die(self, pkt: Die) -> None:
        self.dead_ids.add(pkt.object_id)
        if pkt.object_id in self.npcs:
            self.npcs[pkt.object_id].is_dead = True
        self._dead_timestamps[pkt.object_id] = time.monotonic()
        # Clear buff tracking for dead object (self or party member).
        # Server may not send AbnormalStatusUpdate on death; without this,
        # rebuff_if_missing thinks buffs are still present and waits full interval.
        if pkt.object_id == self.me.object_id:
            self.abnormal_buff_skill_ids.clear()
        self.abnormal_buffs_by_object.pop(pkt.object_id, None)
        self._abnormal_expire_at.pop(pkt.object_id, None)

    def on_skill_list(self, skills: list[tuple[int, int, bool]]) -> None:
        self.my_skills = {sid: lvl for sid, lvl, _ in skills}
        self.passive_skill_ids = {sid for sid, _, passive in skills if passive}
        self.skill_ids_seen_in_skill_list.update(self.my_skills.keys())

    def buff_present_via_skill_list(self, skill_id: int) -> bool | None:
        """Teon / some forks: no usable AbnormalStatusUpdate — infer toggle from SkillList.

        None = this skill id never appeared in SkillList yet (do not treat as «missing»).
        True/False = was seen before; now present with level>0 / absent or level 0.
        """
        if skill_id not in self.skill_ids_seen_in_skill_list:
            return None
        return self.my_skills.get(skill_id, 0) > 0

    def on_magic_skill_launched(self, pkt: MagicSkillLaunched) -> None:
        if not self.me.object_id or pkt.caster_id != self.me.object_id:
            return
        if pkt.skill_id <= 0:
            return
        self.cast_notify_skill_level[pkt.skill_id] = pkt.skill_level

    def buff_present_merged_self(self, skill_id: int) -> bool | None:
        """Self buff «on» for toggles: trust MagicSkillLaunched; SkillList only for definite «off».

        Known skills stay in SkillList with level>0 while aura is off — do not treat that as on.
        """
        me = self.me.object_id
        if me:
            ab = self.abnormal_buff_active(me, skill_id)
            if ab is True:
                return True
            if ab is False:
                if skill_id in self.cast_notify_skill_level:
                    return self.cast_notify_skill_level[skill_id] > 0
                return False
        if skill_id in self.cast_notify_skill_level:
            return self.cast_notify_skill_level[skill_id] > 0
        sl = self.buff_present_via_skill_list(skill_id)
        if sl is False:
            return False
        return None

    def on_item_list(self, pkt: ItemList) -> None:
        self.inventory_by_object.clear()
        for oid, iid, cnt in pkt.items:
            if oid and cnt > 0:
                self.inventory_by_object[oid] = (iid, cnt)

    def on_inventory_update(self, pkt: InventoryUpdate) -> None:
        """Merge SC_InventoryUpdate rows; (oid, 0, 0) removes slot."""
        for oid, iid, cnt in pkt.items:
            if not oid:
                continue
            if (iid == 0 and cnt == 0) or cnt <= 0:
                self.inventory_by_object.pop(oid, None)
            else:
                self.inventory_by_object[oid] = (iid, cnt)

    def object_id_for_item_template(self, template_id: int) -> int | None:
        for oid, (iid, cnt) in self.inventory_by_object.items():
            if iid == template_id and cnt > 0:
                return oid
        return None

    def on_skill_cool_time(self, rows: list[tuple[int, int, int]]) -> None:
        now = time.monotonic()
        # Mis-parsed SkillCoolTime can lock skills for hours — cap reuse delay.
        _MAX_REUSE_SEC = 600.0
        for sid, rem, _tot in rows:
            if rem <= 0:
                self.skill_reuse_ready_at.pop(sid, None)
                continue
            # Most L2J servers send milliseconds; small values may already be seconds.
            sec = rem / 1000.0 if rem > 2000 else float(rem)
            if sec < 0.05:
                sec = rem / 1000.0
            sec = max(0.0, min(sec, _MAX_REUSE_SEC))
            self.skill_reuse_ready_at[sid] = now + sec

    def is_skill_ready(self, skill_id: int) -> bool:
        t = self.skill_reuse_ready_at.get(skill_id)
        if t is None:
            return True
        return time.monotonic() >= t

    def _abnormal_apply_expire_rows(
        self, oid_key: int, effects: list[tuple[int, int, int]]
    ) -> None:
        """Store monotonic expiry per effect skill id (duration usually seconds on L2J)."""
        now = time.monotonic()
        row: dict[int, float] = {}
        for sid, _lvl, dur in effects:
            if dur in (-1, 0xFFFFFFFF):
                row[sid] = now + 86400.0 * 3650
            elif dur > 10_000_000:
                row[sid] = now + min(max(dur / 1000.0, 0.5), 600.0)
            elif dur > 0:
                row[sid] = now + float(dur)
        self._abnormal_expire_at[oid_key] = row

    def on_abnormal_status_update(
        self,
        object_id: int,
        effects: list[tuple[int, int, int]],
        *,
        explicit_empty: bool = False,
    ) -> None:
        sids = {sid for sid, _, _ in effects}
        # Layout A: no objectId in packet → treat as self when we know me.object_id
        oid_key = object_id
        if object_id == 0 and self.me.object_id:
            oid_key = self.me.object_id
        if explicit_empty:
            self.abnormal_buffs_by_object[oid_key] = set()
            self._abnormal_expire_at.pop(oid_key, None)
            if self.me.object_id and oid_key == self.me.object_id:
                self.abnormal_buff_skill_ids = set()
            return
        # Mis-parsed or stub 0x7F often yields [] — wiping would mark every buff «missing» and spam rebuff.
        if not sids:
            return
        self.abnormal_buffs_by_object[oid_key] = set(sids)
        self._abnormal_apply_expire_rows(oid_key, effects)
        if self.me.object_id and oid_key == self.me.object_id:
            self.abnormal_buff_skill_ids = set(sids)

    def on_party_spelled(self, object_id: int, effects: list[tuple[int, int, int]]) -> None:
        """Merge PartySpelled into per-object buff ids (party members / pets)."""
        if object_id == 0 or not effects:
            return
        sids = {sid for sid, _, _ in effects}
        self.abnormal_buffs_by_object[object_id] = set(sids)
        self._abnormal_apply_expire_rows(object_id, effects)
        if self.me.object_id and object_id == self.me.object_id:
            self.abnormal_buff_skill_ids = set(sids)

    def on_short_buff_status_update(self, pkt_skill_id: int, pkt_object_id: int = 0) -> None:
        """Short icon row: treat as hint for self when oid matches or packet had no oid."""
        me = self.me.object_id
        if not me or pkt_skill_id <= 0:
            return
        oid = pkt_object_id if pkt_object_id else me
        if oid != me:
            self.abnormal_buffs_by_object.setdefault(oid, set()).add(pkt_skill_id)
            return
        self.abnormal_buff_skill_ids.add(pkt_skill_id)
        self.abnormal_buffs_by_object.setdefault(me, set()).add(pkt_skill_id)

    def register_attacker_on_me(self, attacker_object_id: int) -> None:
        if attacker_object_id:
            self._attackers_on_me[attacker_object_id] = time.monotonic()

    def is_npc_attacking_me(self, npc_object_id: int, *, window_sec: float = 8.0) -> bool:
        t = self._attackers_on_me.get(npc_object_id)
        if t is None:
            return False
        return (time.monotonic() - t) < window_sec

    def abnormal_buff_active(self, object_id: int, skill_id: int) -> bool | None:
        """Whether skill_id is considered active from abnormal + expiry; None = unknown."""
        if object_id == 0:
            return None
        now = time.monotonic()
        if skill_id in self.abnormal_buffs_by_object.get(object_id, set()):
            exp = self._abnormal_expire_at.get(object_id, {}).get(skill_id)
            if exp is not None and now >= exp:
                return False
            return True
        exp = self._abnormal_expire_at.get(object_id, {}).get(skill_id)
        if exp is not None:
            return now < exp
        return None

    def abnormal_skill_ids_for_object(self, object_id: int) -> set[int]:
        """Buff effect skill ids last seen for this object (empty if never updated)."""
        if object_id == 0:
            return set()
        return set(self.abnormal_buffs_by_object.get(object_id, set()))

    def abnormal_reported_for_object(self, object_id: int) -> bool:
        """True after at least one AbnormalStatusUpdate was applied for this object id.

        Before the first packet, abnormal_skill_ids_for_object returns empty set — same as
        «no buffs» and would cause endless «rebuff if missing» without this guard.
        """
        if object_id == 0:
            return False
        return object_id in self.abnormal_buffs_by_object

    def cleanup_dead(self, max_age: float = 30.0) -> int:
        """Remove NPCs that have been dead for more than max_age seconds."""
        now = time.monotonic()
        to_remove = [
            oid for oid, t in self._dead_timestamps.items()
            if now - t > max_age
        ]
        for oid in to_remove:
            self.npcs.pop(oid, None)
            self.dead_ids.discard(oid)
            del self._dead_timestamps[oid]
        return len(to_remove)

    # ------------------------------------------------------------------ #
    # Query helpers
    # ------------------------------------------------------------------ #

    def dist(self, x1: int, y1: int, x2: int, y2: int) -> float:
        return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

    def dist_to(self, npc: Npc) -> float:
        return self.dist(self.me.x, self.me.y, npc.x, npc.y)

    def dist_to_npc_3d(self, npc: Npc) -> float:
        """3D distance for combat / retain (hills, flying mobs)."""
        dx = npc.x - self.me.x
        dy = npc.y - self.me.y
        dz = npc.z - self.me.z
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    @staticmethod
    def dist_xyz(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int) -> float:
        dx = x2 - x1
        dy = y2 - y1
        dz = z2 - z1
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def any_living_attacker_threatens_me(self, window_sec: float = 8.0) -> bool:
        """True if a registered attacker oid is still a living attackable NPC within the time window."""
        now = time.monotonic()
        for oid, t in list(self._attackers_on_me.items()):
            if now - t >= window_sec:
                continue
            n = self.npcs.get(oid)
            if n and n.is_attackable and not n.looks_eliminated():
                return True
        return False

    def nearest_aggro_npc_except(
        self,
        exclude_oid: int,
        max_dist: float,
        *,
        target_z_range_max: float,
        npc_blacklist: frozenset[int],
        attack_only_whitelist: bool,
        npc_whitelist: frozenset[int],
        skip_summoned: bool,
        never_attack_oids: frozenset[int],
        aggro_window_sec: float,
        kill_cooldown: float = 5.0,
        anchor_xyz: tuple[int, int, int] | None = None,
        anchor_leash_radius: float = 0.0,
    ) -> Optional[Npc]:
        """Closest 3D distance NPC that recently hit me, excluding exclude_oid."""
        me = self.me
        mz = me.z
        now = time.monotonic()
        whitelist_on = attack_only_whitelist and bool(npc_whitelist)

        def skip_npc(npc: Npc) -> bool:
            if npc.object_id == exclude_oid:
                return True
            if npc.object_id in never_attack_oids:
                return True
            if skip_summoned and npc.is_summoned:
                return True
            if npc.npc_id in npc_blacklist:
                return True
            if whitelist_on and npc.npc_id not in npc_whitelist:
                return True
            if target_z_range_max > 0 and abs(npc.z - mz) > target_z_range_max:
                return True
            return False

        def anchor_ok(npc: Npc) -> bool:
            if not anchor_xyz or anchor_leash_radius <= 0:
                return True
            ax, ay, az = anchor_xyz
            return self.dist_xyz(ax, ay, az, npc.x, npc.y, npc.z) <= anchor_leash_radius

        best: Optional[Npc] = None
        best_d = float("inf")
        for npc in self.npcs.values():
            if not npc.is_attackable or npc.looks_eliminated():
                continue
            if skip_npc(npc):
                continue
            if not self.is_npc_attacking_me(npc.object_id, window_sec=aggro_window_sec):
                continue
            death_time = self._dead_timestamps.get(npc.object_id)
            if death_time and now - death_time < kill_cooldown:
                continue
            d = self.dist_to_npc_3d(npc)
            if d > max_dist:
                continue
            if not anchor_ok(npc):
                continue
            if d < best_d:
                best_d = d
                best = npc
        return best

    def get_nearest_mob(self, max_dist: float = 2000.0, kill_cooldown: float = 5.0) -> Optional[Npc]:
        """Return nearest alive attackable NPC within max_dist, or None.
        Skips mobs whose objectId was recently killed (within kill_cooldown seconds)."""
        return self.pick_auto_combat_target(
            max_dist,
            prefer_aggro=False,
            retain_target_oid=0,
            retain_max_dist=0.0,
            npc_blacklist=frozenset(),
            attack_only_whitelist=False,
            npc_whitelist=frozenset(),
            target_z_range_max=DEFAULT_TARGET_Z_RANGE_MAX,
            skip_summoned=False,
            never_attack_oids=frozenset(),
            kill_cooldown=kill_cooldown,
        )

    def pick_auto_combat_target(
        self,
        max_dist: float,
        *,
        prefer_aggro: bool,
        retain_target_oid: int,
        retain_max_dist: float,
        npc_blacklist: frozenset[int],
        attack_only_whitelist: bool,
        npc_whitelist: frozenset[int],
        target_z_range_max: float,
        skip_summoned: bool,
        never_attack_oids: frozenset[int],
        kill_cooldown: float = 5.0,
        aggro_window_sec: float = 8.0,
        anchor_xyz: tuple[int, int, int] | None = None,
        anchor_leash_radius: float = 0.0,
    ) -> Optional[Npc]:
        """Select combat target: optional retain current, aggro priority, blacklist / Z / summons."""
        me = self.me
        now = time.monotonic()
        mz = me.z
        whitelist_on = attack_only_whitelist and bool(npc_whitelist)

        def anchor_ok(npc: Npc) -> bool:
            if not anchor_xyz or anchor_leash_radius <= 0:
                return True
            ax, ay, az = anchor_xyz
            return self.dist_xyz(ax, ay, az, npc.x, npc.y, npc.z) <= anchor_leash_radius

        def skip_npc(npc: Npc) -> bool:
            if npc.object_id in never_attack_oids:
                return True
            if skip_summoned and npc.is_summoned:
                return True
            if npc.npc_id in npc_blacklist:
                return True
            if whitelist_on and npc.npc_id not in npc_whitelist:
                return True
            if target_z_range_max > 0 and abs(npc.z - mz) > target_z_range_max:
                return True
            return False

        def in_range(npc: Npc) -> bool:
            if self.dist_to_npc_3d(npc) > max_dist:
                return False
            if not anchor_ok(npc):
                return False
            death_time = self._dead_timestamps.get(npc.object_id)
            if death_time and now - death_time < kill_cooldown:
                return False
            return True

        if retain_target_oid and retain_max_dist > 0:
            cur = self.npcs.get(retain_target_oid)
            if (
                cur
                and cur.is_attackable
                and not cur.looks_eliminated()
                and not skip_npc(cur)
                and in_range(cur)
                and self.dist_to_npc_3d(cur) <= retain_max_dist
                and anchor_ok(cur)
            ):
                return cur

        candidates: list[Npc] = []
        for npc in self.npcs.values():
            if not npc.is_attackable or npc.looks_eliminated():
                continue
            if skip_npc(npc):
                continue
            if not in_range(npc):
                continue
            candidates.append(npc)

        if not candidates:
            return None

        def sort_key(n: Npc) -> tuple[int | float, float]:
            d = self.dist_to_npc_3d(n)
            if prefer_aggro:
                agg = 0 if self.is_npc_attacking_me(n.object_id, window_sec=aggro_window_sec) else 1
                return (agg, d)
            return (d, 0.0)

        candidates.sort(key=sort_key)
        return candidates[0]

    def get_items_in_range(self, max_dist: float = 800.0) -> list[GroundItem]:
        """Return all ground items within max_dist, sorted by distance."""
        result = [
            item for item in self.ground_items.values()
            if self.dist(self.me.x, self.me.y, item.x, item.y) <= max_dist
        ]
        result.sort(key=lambda it: self.dist(self.me.x, self.me.y, it.x, it.y))
        return result

    def get_mobs_in_range(
        self,
        max_dist: float = 2000.0,
        kill_cooldown: float = 5.0,
        *,
        attackable_only: bool = True,
    ) -> list[Npc]:
        """NPCs within max_dist, sorted by distance. Default: attackable only (combat list).
        attackable_only=False includes peace NPCs for UI/debug (still excludes dead / 0 HP)."""
        now = time.monotonic()

        def _ok(npc: Npc) -> bool:
            if npc.looks_eliminated():
                return False
            if self.dist_to(npc) > max_dist:
                return False
            death_time = self._dead_timestamps.get(npc.object_id)
            if death_time and now - death_time < kill_cooldown:
                return False
            if attackable_only and not npc.is_attackable:
                return False
            return True

        result = [npc for npc in self.npcs.values() if _ok(npc)]
        result.sort(key=self.dist_to)
        return result
