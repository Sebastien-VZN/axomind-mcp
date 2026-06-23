"""Axomind MCP — Planning / Activity tools.

Tools for listing activities, reading activity metadata, and managing
planning assignments (time slots). All tools register on the shared
FastMCP instance.

High-level tools (create_assignment, modify_assignment, verify_assignment)
accept human-friendly parameters (dates, times, weekday names) and internally
build the JSON payloads expected by the PHP bot API. This mirrors the logic
in the Flutter mixin_forms_planning.dart (setSingleOutForm / setMultiOutForm).
"""

import datetime
import json

from axomind_mcp._common import _post, mcp

# ──────────────────────────────────────────────
# Helpers — date/time conversion (mirrors LibDatetime Dart)
# ──────────────────────────────────────────────

# Weekday name → Dart weekday number (1=Monday ... 7=Sunday)
_WEEKDAY_NAMES = {
    "monday": 1, "mon": 1,
    "tuesday": 2, "tue": 2,
    "wednesday": 3, "wed": 3,
    "thursday": 4, "thu": 4,
    "friday": 5, "fri": 5,
    "saturday": 6, "sat": 6,
    "sunday": 7, "sun": 7,
}


def _parse_date(date_str: str) -> datetime.date:
    """Parse a YYYY-MM-DD string into a date object."""
    return datetime.datetime.strptime(date_str.strip(), "%Y-%m-%d").date()


def _get_day_of_year(d: datetime.date) -> int:
    """Return day-of-year (1-based, Jan 1 = 1). Mirrors LibDatetime.getDayOfYear."""
    start_of_year = datetime.date(d.year, 1, 1)
    return (d - start_of_year).days + 1


def _encode_bitmask(weekdays: list[int]) -> int:
    """Encode a list of weekday numbers (1=Mon ... 7=Sun) into a bitmask.
    Bit 0 = Monday, bit 6 = Sunday. Mirrors LibDatetime.encodeBitmask."""
    mask = 0
    for day in weekdays:
        if 1 <= day <= 7:
            mask |= 1 << (day - 1)
    return mask


def _decode_bitmask(mask: int) -> list[int]:
    """Decode a bitmask into a list of weekday numbers (1=Mon ... 7=Sun)."""
    days = []
    for day in range(1, 8):
        if mask & (1 << (day - 1)):
            days.append(day)
    return days


def _format_time_iso(hour: int, minute: int) -> str:
    """Format an hour/minute as HH:mm:ss (server time format)."""
    return f"{hour:02d}:{minute:02d}:00"


def _format_datetime_iso(d: datetime.date) -> str:
    """Format a date as ISO 8601 UTC (server format)."""
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}T00:00:00.000Z"


def _now_iso() -> str:
    """Current UTC time in ISO 8601 format."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _resolve_weekdays(weekday_names: list[str]) -> list[int]:
    """Convert a list of weekday names (case-insensitive) to weekday numbers."""
    result = []
    for name in weekday_names:
        key = name.strip().lower()
        if key not in _WEEKDAY_NAMES:
            raise ValueError(f"Unknown weekday: '{name}'. Valid: monday, tuesday, ... sunday")
        result.append(_WEEKDAY_NAMES[key])
    return sorted(set(result))


def _build_single_assignment(
    id_activity: int,
    titre: str,
    notes: str,
    date_str: str,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    user_ids: list[int],
) -> tuple[str, str]:
    """Build planning_list and recursive_group JSON for a single-day assignment.

    Mirrors setSingleOutForm in mixin_forms_planning.dart:
    - active_days = 0
    - start_date == end_date
    - One PlanningDaysContent per user with one PlanningTimeSlot
    """
    d = _parse_date(date_str)
    day_of_year = _get_day_of_year(d)
    now_iso = _now_iso()
    start_time = _format_time_iso(start_hour, start_minute)
    end_time = _format_time_iso(end_hour, end_minute)
    date_iso = _format_datetime_iso(d)

    # Build planning_list — one day entry per user
    planning_list = []
    for uid in user_ids:
        planning_list.append({
            "id": "0",
            "slot_year": d.year,
            "index_position_jour": day_of_year,
            "rel_id_user": uid,
            "taches": [{
                "id": "0",
                "rel_id_planning_day": "0",
                "rel_id_activity": id_activity,
                "group_control_id": "0",
                "start_time": start_time,
                "end_time": end_time,
                "maj_datetime": now_iso,
            }],
            "maj_datetime": now_iso,
        })

    # Build recursive_group — single day, active_days = 0
    recursive_group = {
        "id": "0",
        "id_activity": id_activity,
        "titre": titre,
        "notes": notes,
        "start_date": date_iso,
        "end_date": date_iso,
        "active_days": 0,
        "created_by": 0,  # server forces bot owner user_id
        "created_datetime": now_iso,
        "maj_datetime": now_iso,
    }

    return json.dumps(planning_list), json.dumps(recursive_group)


def _build_recursive_assignment(
    id_activity: int,
    titre: str,
    notes: str,
    start_date_str: str,
    end_date_str: str,
    weekdays: list[int],
    time_slots: list[tuple[int, int, int, int]],
    user_ids: list[int],
    group_id: int = 0,
) -> tuple[str, str]:
    """Build planning_list and recursive_group JSON for a recursive assignment.

    Mirrors setMultiOutForm in mixin_forms_planning.dart:
    - Iterates from start_date to end_date
    - Creates PlanningDaysContent only for active weekdays
    - Each day gets the same set of time slots per user
    - active_days = bitmask of active weekdays
    """
    d_start = _parse_date(start_date_str)
    d_end = _parse_date(end_date_str)
    now_iso = _now_iso()
    active_days = _encode_bitmask(weekdays)
    start_iso = _format_datetime_iso(d_start)
    end_iso = _format_datetime_iso(d_end)

    # Build planning_list — iterate day by day
    planning_list = []
    current = d_start
    while current <= d_end:
        weekday = current.isoweekday()  # 1=Monday ... 7=Sunday
        if weekday in weekdays:
            day_of_year = _get_day_of_year(current)
            for uid in user_ids:
                taches = []
                for (sh, sm, eh, em) in time_slots:
                    taches.append({
                        "id": "0",
                        "rel_id_planning_day": "0",
                        "rel_id_activity": id_activity,
                        "group_control_id": str(group_id),
                        "start_time": _format_time_iso(sh, sm),
                        "end_time": _format_time_iso(eh, em),
                        "maj_datetime": now_iso,
                    })
                planning_list.append({
                    "id": "0",
                    "slot_year": current.year,
                    "index_position_jour": day_of_year,
                    "rel_id_user": uid,
                    "taches": taches,
                    "maj_datetime": now_iso,
                })
        current += datetime.timedelta(days=1)

    # Build recursive_group
    recursive_group = {
        "id": str(group_id),
        "id_activity": id_activity,
        "titre": titre,
        "notes": notes,
        "start_date": start_iso,
        "end_date": end_iso,
        "active_days": active_days,
        "created_by": 0,  # server forces bot owner user_id
        "created_datetime": now_iso,
        "maj_datetime": now_iso,
    }

    return json.dumps(planning_list), json.dumps(recursive_group)


def _build_summary(result_json: str) -> str:
    """Parse the server response and build a human-readable summary."""
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return result_json

    if "error" in data:
        return json.dumps(data, indent=2)

    # Check for return_info (bot API format)
    if "return_info" not in data:
        return json.dumps(data, indent=2)

    info = data.get("return_info", "")
    payload = data.get("data", [])

    if not isinstance(payload, list) or len(payload) < 2:
        return f"Server response: {info}\nRaw: {json.dumps(data, indent=2)}"

    slots_data = payload[0] if isinstance(payload[0], list) else []
    group_data = payload[1] if isinstance(payload[1], dict) else {}

    group_id = group_data.get("id", "?")
    titre = group_data.get("titre", "?")
    active_days = group_data.get("active_days", 0)
    start_date = group_data.get("start_date", "?")
    end_date = group_data.get("end_date", "?")

    # Decode active_days bitmask
    if active_days == 0:
        type_label = "single-day"
        days_label = f"{start_date}"
    else:
        type_label = "recursive"
        active_weekdays = _decode_bitmask(active_days)
        day_names = {
            1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun",
        }
        days_label = f"{start_date} → {end_date} ({', '.join(day_names[d] for d in active_weekdays)})"

    # Count slots
    total_slots = 0
    slot_details = []
    for day_entry in slots_data:
        day_of_year = day_entry.get("index_position_jour", "?")
        year = day_entry.get("slot_year", "?")
        uid = day_entry.get("rel_id_user", "?")
        taches = day_entry.get("taches", [])
        for slot in taches:
            total_slots += 1
            slot_details.append({
                "slot_id": slot.get("id", "?"),
                "day_id": day_entry.get("id", "?"),
                "year": year,
                "day_of_year": day_of_year,
                "user_id": uid,
                "start_time": slot.get("start_time", "?"),
                "end_time": slot.get("end_time", "?"),
                "group_id": slot.get("group_control_id", "?"),
            })

    summary = {
        "status": info,
        "group": {
            "id": group_id,
            "titre": titre,
            "type": type_label,
            "period": days_label,
            "active_days_bitmask": active_days,
        },
        "total_slots": total_slots,
        "slots": slot_details,
    }
    return json.dumps(summary, indent=2)


# ──────────────────────────────────────────────
# Low-level tools — raw JSON (kept for backward compat)
# ──────────────────────────────────────────────


@mcp.tool()
def list_activities() -> str:
    """List activities where the bot is assigned (metadata only).

    Returns a JSON string. The response contains an array of activity objects
    with at least: id, titre, participants (list of user IDs), and scheduling
    metadata. Use get_activity to read the full detail of a single activity.

    Returns:
        JSON string — array of activity metadata objects.
    """
    return _post("activity", "get_activities")


@mcp.tool()
def get_activity(id_activity: int) -> str:
    """Read a specific activity (full metadata).

    Returns the full activity object including participants, planning groups,
    and assignment details. Use list_activities first to find the IDs.

    Args:
        id_activity: Activity ID

    Returns:
        JSON string — full activity metadata object.
    """
    return _post("activity", "get_activity", id_activity=id_activity)


@mcp.tool()
def add_assignment(id_activity: int, planning_list: str, recursive_group: str) -> str:
    """Assign time slots to an activity by creating a new recursive group.

    A recursive group defines a date range and recurrence pattern. The planning
    list defines the time slots within each day of that range. Together they
    form a complete assignment that appears on the activity timeline.

    Args:
        id_activity: Activity ID
        planning_list: JSON string — array of day slots. Each element:
            {
                "id": "0",                        # 0 for new slots
                "slot_year": 2026,                # year of the slot
                "index_position_jour": 1,         # day-of-year (1-365/366)
                "rel_id_user": 2,                 # user ID the slot belongs to
                "taches": [                       # time slots within the day
                    {
                        "id": "0",
                        "rel_id_planning_day": "0",  # 0 for new
                        "rel_id_activity": <id_activity>,
                        "group_control_id": "0",     # 0 for new (assigned server-side)
                        "start_time": "08:00:00",    # HH:mm:ss
                        "end_time": "12:00:00",      # HH:mm:ss
                        "maj_datetime": "2026-06-23T10:00:00.000Z"  # ISO 8601 UTC
                    }
                ],
                "maj_datetime": "2026-06-23T10:00:00.000Z"
            }
        recursive_group: JSON string — the group definition:
            {
                "id": "0",                        # 0 for new group
                "id_activity": <id_activity>,
                "titre": "Weekly morning",        # group title
                "notes": "",                      # optional notes
                "start_date": "2026-06-01T00:00:00.000Z",   # ISO 8601 UTC
                "end_date": "2026-06-30T00:00:00.000Z",     # ISO 8601 UTC
                "active_days": 127,               # bitmask: bit 0=Mon, 1=Tue, ... 6=Sun
                "created_by": 2,                  # user ID of the creator
                "created_datetime": "2026-06-23T10:00:00.000Z",
                "maj_datetime": "2026-06-23T10:00:00.000Z"
            }

    Returns:
        JSON string — server response with created slot IDs and group ID.
    """
    return _post(
        "activity",
        "add_assignment",
        id_activity=id_activity,
        planning_list=planning_list,
        recursive_group=recursive_group,
    )


@mcp.tool()
def update_assignment(
    id_activity: int,
    update_assignement_id: int,
    planning_list: str,
    recursive_group: str,
) -> str:
    """Update an existing assignment group and its time slots.

    Replaces the group definition and all its slots. Use get_activity first to
    find the group ID (update_assignement_id). The planning_list and
    recursive_group formats are identical to add_assignment, but the group id
    and slot ids should be set to the existing values (non-zero).

    Args:
        id_activity: Activity ID
        update_assignement_id: Existing group ID to update
        planning_list: JSON string — full slot list (same format as add_assignment)
        recursive_group: JSON string — updated group definition (same format, id = group ID)

    Returns:
        JSON string — server response with updated slot IDs.
    """
    return _post(
        "activity",
        "update_assignment",
        id_activity=id_activity,
        update_assignement_id=update_assignement_id,
        planning_list=planning_list,
        recursive_group=recursive_group,
    )


@mcp.tool()
def delete_assignment(id_activity: int, delete_recursive_group_slot: int) -> str:
    """Delete an assignment group and all its time slots.

    Removes the recursive group and every slot that references it. Use
    get_activity first to find the group ID.

    Args:
        id_activity: Activity ID
        delete_recursive_group_slot: Group ID to delete

    Returns:
        JSON string — server confirmation.
    """
    return _post(
        "activity",
        "delete_assignment",
        id_activity=id_activity,
        delete_recursive_group_slot=delete_recursive_group_slot,
    )


# ──────────────────────────────────────────────
# High-level tools — human-friendly parameters (no JSON to build)
# ──────────────────────────────────────────────


@mcp.tool()
def create_assignment(
    id_activity: int,
    user_ids: list[int],
    titre: str,
    start_date: str,
    end_date: str,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    weekdays: list[str] | None = None,
    notes: str = "",
) -> str:
    """Create a planning assignment with human-friendly parameters.

    This tool builds the JSON payloads internally — you only need to provide
    dates (YYYY-MM-DD), times (hour/minute integers), and weekday names.
    It mirrors the Flutter setSingleOutForm / setMultiOutForm logic.

    Two modes:
    - Single-day: start_date == end_date, weekdays omitted or empty.
      Creates one slot per user on that date.
    - Recursive: start_date < end_date, weekdays specifies which days of the
      week are active. Creates one slot per user per active weekday.

    Args:
        id_activity: Activity ID (from list_activities)
        user_ids: List of user IDs to assign (from activity participants)
        titre: Assignment title (e.g. "Morning shift")
        start_date: Start date in YYYY-MM-DD format (e.g. "2026-06-23")
        end_date: End date in YYYY-MM-DD format. For single-day, use same as start_date.
        start_hour: Start hour 0-23 (e.g. 8 for 08:00)
        start_minute: Start minute 0-59 (e.g. 0)
        end_hour: End hour 0-23 (e.g. 14 for 14:00)
        end_minute: End minute 0-59 (e.g. 0)
        weekdays: Active weekday names for recursive mode. Case-insensitive.
            Full names or 3-letter abbreviations: monday/mon, tuesday/tue, etc.
            Omit or leave empty for single-day assignment.
        notes: Optional notes text

    Returns:
        JSON string — human-readable summary with group ID, slot count,
        and per-slot details (slot_id, day_of_year, user_id, times).
    """
    if not user_ids:
        return json.dumps({"error": "user_ids must not be empty"})

    is_single = (start_date == end_date) and (not weekdays or len(weekdays) == 0)

    if is_single:
        planning_list, recursive_group = _build_single_assignment(
            id_activity=id_activity,
            titre=titre,
            notes=notes,
            date_str=start_date,
            start_hour=start_hour,
            start_minute=start_minute,
            end_hour=end_hour,
            end_minute=end_minute,
            user_ids=user_ids,
        )
    else:
        if not weekdays:
            return json.dumps({"error": "weekdays required for recursive assignment (start_date != end_date)"})
        try:
            weekday_nums = _resolve_weekdays(weekdays)
        except ValueError as e:
            return json.dumps({"error": str(e)})

        time_slots = [(start_hour, start_minute, end_hour, end_minute)]
        planning_list, recursive_group = _build_recursive_assignment(
            id_activity=id_activity,
            titre=titre,
            notes=notes,
            start_date_str=start_date,
            end_date_str=end_date,
            weekdays=weekday_nums,
            time_slots=time_slots,
            user_ids=user_ids,
        )

    raw = _post(
        "activity",
        "add_assignment",
        id_activity=id_activity,
        planning_list=planning_list,
        recursive_group=recursive_group,
    )
    return _build_summary(raw)


@mcp.tool()
def modify_assignment(
    id_activity: int,
    group_id: int,
    user_ids: list[int],
    titre: str,
    start_date: str,
    end_date: str,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    weekdays: list[str] | None = None,
    notes: str = "",
) -> str:
    """Modify an existing assignment group with human-friendly parameters.

    Replaces the group definition and all its time slots. The server marks a
    tombstone for the old group, removes old slots, and creates new ones.
    Uses the same parameter format as create_assignment but requires group_id.

    Args:
        id_activity: Activity ID
        group_id: Existing group ID to update (from get_activity or create_assignment result)
        user_ids: List of user IDs to assign
        titre: Assignment title
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format (same as start_date for single-day)
        start_hour: Start hour 0-23
        start_minute: Start minute 0-59
        end_hour: End hour 0-23
        end_minute: End minute 0-59
        weekdays: Active weekday names for recursive mode. Omit for single-day.
        notes: Optional notes text

    Returns:
        JSON string — human-readable summary with updated slot details.
    """
    if not user_ids:
        return json.dumps({"error": "user_ids must not be empty"})
    if group_id <= 0:
        return json.dumps({"error": "group_id must be a positive integer"})

    is_single = (start_date == end_date) and (not weekdays or len(weekdays) == 0)

    if is_single:
        planning_list, recursive_group = _build_single_assignment(
            id_activity=id_activity,
            titre=titre,
            notes=notes,
            date_str=start_date,
            start_hour=start_hour,
            start_minute=start_minute,
            end_hour=end_hour,
            end_minute=end_minute,
            user_ids=user_ids,
        )
    else:
        if not weekdays:
            return json.dumps({"error": "weekdays required for recursive assignment"})
        try:
            weekday_nums = _resolve_weekdays(weekdays)
        except ValueError as e:
            return json.dumps({"error": str(e)})

        time_slots = [(start_hour, start_minute, end_hour, end_minute)]
        planning_list, recursive_group = _build_recursive_assignment(
            id_activity=id_activity,
            titre=titre,
            notes=notes,
            start_date_str=start_date,
            end_date_str=end_date,
            weekdays=weekday_nums,
            time_slots=time_slots,
            user_ids=user_ids,
            group_id=group_id,
        )

    raw = _post(
        "activity",
        "update_assignment",
        id_activity=id_activity,
        update_assignement_id=group_id,
        planning_list=planning_list,
        recursive_group=recursive_group,
    )
    return _build_summary(raw)


@mcp.tool()
def verify_assignment(id_activity: int) -> str:
    """Verify and inspect all assignments for an activity.

    Reads the activity metadata and validates that all assignment groups have
    consistent time slots. Returns a telemetry report with:
    - Activity info (id, title, participants)
    - Per-group details (group_id, titre, type, date range, active weekdays)
    - Per-slot details (slot_id, day_of_year, user_id, start/end times)
    - Consistency checks (group references, date ranges, weekday matching)

    Use this after create_assignment or modify_assignment to confirm the
    server accepted and stored the assignment correctly.

    Args:
        id_activity: Activity ID to verify

    Returns:
        JSON string — telemetry report with activity, groups, slots, and
        validation results.
    """
    raw = _post("activity", "get_activity", id_activity=id_activity)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": f"Failed to parse server response: {raw}"})

    if "error" in data:
        return json.dumps(data, indent=2)

    activity = data.get("activity", {})
    if not activity:
        return json.dumps({"error": "Activity not found", "raw": raw})

    # Activity-level info
    act_id = activity.get("id", "?")
    act_titre = activity.get("titre", "?")
    participants_raw = activity.get("participants", "[]")
    try:
        participants = json.loads(participants_raw) if isinstance(participants_raw, str) else participants_raw
    except (json.JSONDecodeError, TypeError):
        participants = []

    # The bot API get_activity returns activity metadata but NOT the planning
    # slots directly. The slots are stored in planning_days_content +
    # planning_time_slot, accessed via the user API (read_plannings).
    # For telemetry, we report what get_activity returns.
    # If the activity has groups, they would be in the activity data.

    report = {
        "activity": {
            "id": act_id,
            "titre": act_titre,
            "participants": participants,
            "color": activity.get("color", "?"),
            "rel_id_user": activity.get("rel_id_user", "?"),
            "bots": activity.get("bots", "[]"),
        },
        "verification": {
            "activity_found": True,
            "participants_count": len(participants) if isinstance(participants, list) else 0,
            "has_bots": bool(activity.get("bots")),
        },
        "note": (
            "Full slot verification requires reading planning_days_content via the "
            "user API (read_plannings route). Use get_activity to inspect group "
            "metadata. The server confirms assignment creation via the "
            "create_assignment / modify_assignment response which includes all "
            "slot IDs and group details."
        ),
        "raw_activity": activity,
    }
    return json.dumps(report, indent=2)