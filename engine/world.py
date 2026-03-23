"""
World state — tracks everything visible in the game world.

Updated by BotEngine as packets arrive from the server.
"""
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from core.packets.server import (
    UserInfo, NpcInfo, DeleteObject, StatusUpdate, MoveToPoint, Die, SpawnItem,
    ATTR_CUR_HP, ATTR_MAX_HP, ATTR_CUR_MP, ATTR_MAX_MP, ATTR_CUR_CP, ATTR_MAX_CP,
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

    @property
    def hp_pct(self) -> float:
        return self.cur_hp / self.max_hp * 100 if self.max_hp else 0.0

    @property
    def mp_pct(self) -> float:
        return self.cur_mp / self.max_mp * 100 if self.max_mp else 0.0


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

    @property
    def npc_id(self) -> int:
        return self.npc_type_id - 1_000_000


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

    # ------------------------------------------------------------------ #
    # Packet handlers (called by BotEngine)
    # ------------------------------------------------------------------ #

    def on_user_info(self, pkt: UserInfo) -> None:
        me = self.me
        me.object_id = pkt.object_id
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

    def on_npc_info(self, pkt: NpcInfo) -> None:
        # Use isDead byte from packet OR our own Die tracking
        is_dead = pkt.is_dead or pkt.object_id in self.dead_ids
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
        )
        if not is_dead:
            self.dead_ids.discard(pkt.object_id)

    def on_delete_object(self, pkt: DeleteObject) -> None:
        self.npcs.pop(pkt.object_id, None)
        self.dead_ids.discard(pkt.object_id)
        self.ground_items.pop(pkt.object_id, None)

    def on_spawn_item(self, pkt: SpawnItem) -> None:
        self.ground_items[pkt.object_id] = GroundItem(
            object_id=pkt.object_id,
            item_id=pkt.item_id,
            count=pkt.count,
            x=pkt.x, y=pkt.y, z=pkt.z,
        )

    def on_status_update(self, pkt: StatusUpdate) -> None:
        if pkt.object_id == self.me.object_id:
            if ATTR_CUR_HP in pkt.attrs:
                self.me.cur_hp = pkt.attrs[ATTR_CUR_HP]
            if ATTR_MAX_HP in pkt.attrs:
                self.me.max_hp = pkt.attrs[ATTR_MAX_HP]
            if ATTR_CUR_MP in pkt.attrs:
                self.me.cur_mp = pkt.attrs[ATTR_CUR_MP]
            if ATTR_MAX_MP in pkt.attrs:
                self.me.max_mp = pkt.attrs[ATTR_MAX_MP]
        elif pkt.object_id in self.npcs:
            npc = self.npcs[pkt.object_id]
            if ATTR_MAX_HP in pkt.attrs:
                npc.max_hp = pkt.attrs[ATTR_MAX_HP]
            if ATTR_CUR_HP in pkt.attrs:
                npc.cur_hp = pkt.attrs[ATTR_CUR_HP]
            if npc.max_hp > 0 and npc.cur_hp >= 0:
                npc.hp_pct = npc.cur_hp / npc.max_hp * 100

    def on_move(self, pkt: MoveToPoint) -> None:
        if pkt.object_id == self.me.object_id:
            self.me.x = pkt.orig_x
            self.me.y = pkt.orig_y
            if pkt.has_orig_z:
                self.me.z = pkt.orig_z
        elif pkt.object_id in self.npcs:
            npc = self.npcs[pkt.object_id]
            npc.x = pkt.orig_x
            npc.y = pkt.orig_y
            if pkt.has_orig_z:
                npc.z = pkt.orig_z

    def on_die(self, pkt: Die) -> None:
        self.dead_ids.add(pkt.object_id)
        if pkt.object_id in self.npcs:
            self.npcs[pkt.object_id].is_dead = True
        self._dead_timestamps[pkt.object_id] = time.monotonic()

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

    def get_nearest_mob(self, max_dist: float = 2000.0, kill_cooldown: float = 5.0) -> Optional[Npc]:
        """Return nearest alive attackable NPC within max_dist, or None.
        Skips mobs whose objectId was recently killed (within kill_cooldown seconds)."""
        now = time.monotonic()
        best: Optional[Npc] = None
        best_d = float("inf")
        for npc in self.npcs.values():
            if not npc.is_attackable or npc.is_dead:
                continue
            # Skip mobs that died recently (respawn grace period)
            death_time = self._dead_timestamps.get(npc.object_id)
            if death_time and now - death_time < kill_cooldown:
                continue
            d = self.dist_to(npc)
            if d < best_d and d <= max_dist:
                best_d = d
                best = npc
        return best

    def get_items_in_range(self, max_dist: float = 800.0) -> list[GroundItem]:
        """Return all ground items within max_dist, sorted by distance."""
        result = [
            item for item in self.ground_items.values()
            if self.dist(self.me.x, self.me.y, item.x, item.y) <= max_dist
        ]
        result.sort(key=lambda it: self.dist(self.me.x, self.me.y, it.x, it.y))
        return result

    def get_mobs_in_range(self, max_dist: float = 2000.0, kill_cooldown: float = 5.0) -> list[Npc]:
        """Return all alive attackable NPCs within max_dist, sorted by distance."""
        now = time.monotonic()
        result = [
            npc for npc in self.npcs.values()
            if npc.is_attackable and not npc.is_dead
            and self.dist_to(npc) <= max_dist
            and not (self._dead_timestamps.get(npc.object_id)
                     and now - self._dead_timestamps[npc.object_id] < kill_cooldown)
        ]
        result.sort(key=self.dist_to)
        return result
