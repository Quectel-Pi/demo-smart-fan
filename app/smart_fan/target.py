from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class Person:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float = 0.0

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) * 0.5

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) * 0.5

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def closeness(self) -> float:
        # A full-body person close to the fan is taller and their feet are lower
        # in the frame. Confidence and area break remaining ties.
        return self.height * 0.50 + self.y2 * 0.25 + min(1.0, self.area) * 0.15 + self.score * 0.10


@dataclass
class DirectionGroup:
    people: list[Person]
    center_x: float
    count: int = field(init=False)
    nearest: Person = field(init=False)

    def __post_init__(self) -> None:
        self.count = len(self.people)
        self.nearest = max(self.people, key=lambda p: p.closeness)


@dataclass
class TargetChoice:
    valid: bool
    person: Person | None = None
    x: float = 0.5
    y: float = 0.5
    score: float = 0.0
    count: int = 0
    group_count: int = 0
    direction: str = "none"
    reason: str = "ok"
    rejected_small: int = 0
    followable: bool = True

    def as_dict(self) -> dict[str, Any]:
        p = self.person
        return {
            "valid": self.valid,
            "x": self.x,
            "y": self.y,
            "score": self.score,
            "count": self.count,
            "group_count": self.group_count,
            "direction": self.direction,
            "reason": self.reason,
            "rejected_small": self.rejected_small,
            "followable": self.followable,
            "person": None
            if p is None
            else {
                "cx": p.cx,
                "cy": p.cy,
                "x1": p.x1,
                "y1": p.y1,
                "x2": p.x2,
                "y2": p.y2,
                "score": p.score,
            },
        }


def parse_people(
    items: Iterable[dict[str, Any]], image_width: int = 0, image_height: int = 0
) -> list[Person]:
    out: list[Person] = []
    for item in items:
        try:
            x1 = float(item["x1"])
            y1 = float(item["y1"])
            x2 = float(item["x2"])
            y2 = float(item["y2"])
            if (x2 > 1.0 or y2 > 1.0) and image_width > 0 and image_height > 0:
                x1 /= image_width
                x2 /= image_width
                y1 /= image_height
                y2 /= image_height
            p = Person(
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                score=float(item.get("score", 0.0)),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if p.width > 0 and p.height > 0 and 0.0 <= p.cx <= 1.0:
            out.append(p)
    return out


def cluster_by_direction(people: list[Person], max_gap: float = 0.12) -> list[DirectionGroup]:
    ordered = sorted(people, key=lambda p: p.cx)
    groups: list[DirectionGroup] = []
    for person in ordered:
        if not groups or person.cx - groups[-1].center_x > max_gap:
            groups.append(DirectionGroup([person], person.cx))
        else:
            group = groups[-1]
            group.people.append(person)
            group.center_x = sum(p.cx for p in group.people) / len(group.people)
            group.__post_init__()
    return groups


def choose_target(
    people: list[Person],
    *,
    group_distance: float = 0.12,
    prefer_group_count: bool = True,
) -> TargetChoice:
    if not people:
        return TargetChoice(valid=False, direction="none")
    groups = cluster_by_direction(people, max_gap=max(0.02, float(group_distance)))
    if prefer_group_count:
        group = max(groups, key=lambda g: (g.count, g.nearest.closeness, -g.center_x))
    else:
        group = max(groups, key=lambda g: (g.nearest.closeness, g.count, -g.center_x))
    person = group.nearest
    if person.cx < 0.4:
        direction = "left"
    elif person.cx > 0.6:
        direction = "right"
    else:
        direction = "center"
    return TargetChoice(
        valid=True,
        person=person,
        x=person.cx,
        y=person.cy,
        score=person.score,
        count=len(people),
        group_count=group.count,
        direction=direction,
    )


class StableTargetSelector:
    """Keep the current direction unless a new direction is sustained.

    The RKNN detector has no person ID in this lightweight path. A large box
    center jump can therefore be a new person, a false box, or an ID switch.
    Requiring continuity prevents the pan servo from snapping across the room.
    """

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        c = cfg or {}
        self.group_distance = float(c.get("group_distance", 0.12))
        self.prefer_group_count = bool(c.get("prefer_group_count", True))
        self.min_height = float(c.get("min_height", 0.18))
        self.max_height = float(c.get("max_height", 0.98))
        self.min_area = float(c.get("min_area", 0.012))
        self.max_center_jump = float(c.get("max_center_jump", 0.22))
        self.switch_confirm_sec = float(c.get("switch_confirm_sec", 0.8))
        self.detection_hold_sec = float(c.get("detection_hold_sec", 1.0))
        self.last_x: float | None = None
        self.last_seen_at = -1e9
        self.last_choice: TargetChoice | None = None
        self.pending_x: float | None = None
        self.pending_since = 0.0

    def _size_ok(self, p: Person) -> bool:
        return self.min_height <= p.height <= self.max_height and p.area >= self.min_area

    def update(self, people: list[Person], now: float) -> TargetChoice:
        accepted = [p for p in people if self._size_ok(p)]
        rejected_small = len(people) - len(accepted)
        if not accepted:
            self.pending_x = None
            self.pending_since = 0.0
            if (
                self.last_choice is not None
                and now - self.last_seen_at <= self.detection_hold_sec
            ):
                cached = self.last_choice
                return TargetChoice(
                    valid=True,
                    person=cached.person,
                    x=cached.x,
                    y=cached.y,
                    score=cached.score,
                    count=0,
                    group_count=cached.group_count,
                    direction=cached.direction,
                    reason="cached",
                    rejected_small=rejected_small,
                )
            return TargetChoice(valid=False, reason="no_size_qualified_person", rejected_small=rejected_small)

        groups = cluster_by_direction(accepted, max_gap=max(0.02, self.group_distance))
        if self.prefer_group_count:
            best_group = max(groups, key=lambda g: (g.count, g.nearest.closeness))
        else:
            best_group = max(groups, key=lambda g: (g.nearest.closeness, g.count))
        best = best_group.nearest

        # Prefer an already-established nearby person over a freshly appearing
        # distant box. This is the key anti-snap rule.
        if self.last_x is not None and now - self.last_seen_at <= 1.25:
            nearby = [p for p in accepted if abs(p.cx - self.last_x) <= self.max_center_jump]
            if nearby:
                person = min(nearby, key=lambda p: abs(p.cx - self.last_x))
                group = next(g for g in groups if person in g.people)
                choice = TargetChoice(
                    valid=True,
                    person=person,
                    x=person.cx,
                    y=person.cy,
                    score=person.score,
                    count=len(accepted),
                    group_count=group.count,
                    direction=self._direction(person.cx),
                    reason="continuity",
                    rejected_small=rejected_small,
                )
                self._accept(choice, now)
                return choice

            if abs(best.cx - self.last_x) > self.max_center_jump:
                if self.pending_x is None or abs(best.cx - self.pending_x) > self.max_center_jump:
                    self.pending_x = best.cx
                    self.pending_since = now
                pending_age = now - self.pending_since
                if pending_age < self.switch_confirm_sec:
                    return TargetChoice(
                        # The detector still has a person in view. Treat that
                        # as presence so the behavior state does not start an
                        # empty-room search while this large jump is pending.
                        # The follower waits until the new direction is stable.
                        valid=True,
                        person=best,
                        x=best.cx,
                        y=best.cy,
                        score=best.score,
                        count=len(accepted),
                        group_count=best_group.count,
                        direction=self._direction(best.cx),
                        reason="switch_pending",
                        rejected_small=rejected_small,
                        followable=False,
                    )

        choice = TargetChoice(
            valid=True,
            person=best,
            x=best.cx,
            y=best.cy,
            score=best.score,
            count=len(accepted),
            group_count=best_group.count,
            direction=self._direction(best.cx),
            reason="accepted",
            rejected_small=rejected_small,
        )
        self._accept(choice, now)
        return choice

    def _accept(self, choice: TargetChoice, now: float) -> None:
        self.last_x = choice.x
        self.last_seen_at = now
        self.last_choice = choice
        self.pending_x = None
        self.pending_since = 0.0

    @staticmethod
    def _direction(x: float) -> str:
        if x < 0.4:
            return "left"
        if x > 0.6:
            return "right"
        return "center"
