# Route Finder to Route Planner Integration Plan

## Overview
Integrate Route Finder with Route Planner so that when a route is started via context menu, the planned stops appear in Route Planner with visual distinction between "planned (mission not yet accepted)" and "accepted" missions.

## User Requirements (Confirmed)
- **Start Route**: Right-click context menu in Route Finder
- **Mission Acceptance**: Manual marking + auto-detection from capture tab (with right-click "remove" option)
- **Persistence**: Save planned route to file, survives app restart

---

## Architecture

### Data Flow
```
Route Finder                     Route Planner
     |                                |
     | (Start Route - context menu)   |
     v                                |
PlannedRouteManager <-----------------+
     |                                |
     | (planned_route.json)           |
     v                                v
  [Planned Stops]  +  [Accepted Missions] = Combined Display
                                      |
                                      v
                          Color-coded tree view:
                          - Orange: Planned (not accepted)
                          - Green/Blue: Accepted
```

### Auto-Detection Flow (Capture Tab)
```
Capture Tab -> Validate -> Save Mission
                              |
                              v
                     MissionMatcher checks:
                     Does this match a planned objective?
                              |
                              v
                     If match: Mark planned objective as "accepted"
                     Remove from planned, now shows as accepted
```

---

## Implementation Steps

### Phase 1: Data Layer

**1. Create `PlannedRoute` dataclass** (`src/domain/models.py`)
```python
@dataclass
class PlannedRoute:
    stops: List[Stop]              # Route stops from CandidateRoute
    mission_scans: List[Dict]      # Original scan data for reference
    started_at: str                # ISO timestamp

    def get_planned_objectives(self) -> List[Objective]:
        """Get all objectives not yet matched to accepted missions."""
```

**2. Create `PlannedRouteManager`** (`src/planned_route_manager.py`)
- Load/save to `planned_route.json`
- Track which objectives have been matched to accepted missions
- Methods:
  - `start_route(candidate_route: CandidateRoute)`
  - `get_planned_route() -> Optional[PlannedRoute]`
  - `mark_objective_accepted(objective: Objective)`
  - `remove_objective(objective: Objective)` (manual removal)
  - `clear_route()`
  - `save()` / `load()`

**3. Create `MissionMatcher`** (`src/services/mission_matcher.py`)
- Compare objectives: `collect_from`, `deliver_to`, `scu_amount`, `cargo_type`
- Use `location_matcher.normalize_location()` for location comparison
- Methods:
  - `find_matching_planned_objective(accepted_obj, planned_route) -> Optional[Objective]`
  - `objectives_match(obj1, obj2) -> bool`

### Phase 2: Route Finder Integration

**4. Add context menu to Route Finder** (`src/ui/route_finder_tab.py`)
- Right-click on route row -> "Start Route"
- Emit signal: `route_started(CandidateRoute)`
- Show confirmation if another route is active

**5. Wire up in MainWindow** (`src/ui/main_window.py`)
- Connect `route_finder_tab.route_started` signal
- Call `planned_route_manager.start_route()`
- Refresh Route Planner tab
- Switch to Route Planner tab

### Phase 3: Route Planner Display

**6. Modify Route Planner refresh** (`src/ui/route_planner_tab.py`)
- Load planned route from `PlannedRouteManager`
- Merge planned stops with accepted mission route
- Algorithm:
  1. Get accepted missions route (existing logic)
  2. Get planned objectives (not yet accepted)
  3. Merge into combined stop list
  4. Mark each objective as `is_planned=True/False`

**7. Visual distinction**
- **Planned stops/objectives**: Amber/orange palette
  - Stop row: `QColor(80, 60, 40)` - muted amber
  - Details: `QColor(100, 75, 50)` - lighter amber
- **Accepted stops/objectives**: Current green/blue palette (unchanged)
- **Mixed stops**: Show both sections with separator

**8. "Missions to accept" indicator**
- At each planned stop, show count: "(2 missions to accept)"
- Tooltip or expandable section with mission details

**9. Context menu for planned objectives**
- Right-click -> "Remove from plan" (manual removal)
- Right-click -> "Mark as Accepted" (manual acceptance)

### Phase 4: Auto-Detection

**10. Hook into mission save flow** (`src/ui/main_window.py`)
- In `_on_mission_saved()`:
  - Call `MissionMatcher.find_matching_planned_objective()`
  - If match found: `planned_route_manager.mark_objective_accepted()`
  - Refresh Route Planner display

**11. Handle edge cases**
- Partial matches (some objectives match, some don't)
- Multiple missions matching same planned objective
- SCU amount differences (exact match vs flexible)

---

## Files to Modify/Create

| File | Action | Changes |
|------|--------|---------|
| `src/domain/models.py` | MODIFY | Add `PlannedRoute` dataclass |
| `src/planned_route_manager.py` | CREATE | Manage planned route state + persistence |
| `src/services/mission_matcher.py` | CREATE | Match accepted missions to planned objectives |
| `src/ui/route_finder_tab.py` | MODIFY | Add context menu with "Start Route" |
| `src/ui/route_planner_tab.py` | MODIFY | Display merged planned + accepted stops with colors |
| `src/ui/main_window.py` | MODIFY | Wire signals, auto-detection hook |

---

## Color Palette

**Planned (Amber/Orange):**
```python
PLANNED_STOP_COLOR = QColor(80, 60, 40)       # Muted amber for stop rows
PLANNED_DETAIL_COLOR = QColor(100, 75, 50)    # Lighter amber for details
PLANNED_BADGE_COLOR = QColor(180, 120, 40)    # Highlight for "to accept" badge
```

**Accepted (Current - unchanged):**
```python
# Existing destination colors (muted dark)
# Existing mission colors (brighter tints)
```

---

## Stop Display Structure

```
In Cargo Hold (if any)
  - [cargo items with delivery info]

Stop 1: Location Name
  [PLANNED] Pickup: 24 SCU Distilled Spirits -> Destination (Mission to accept)
  [ACCEPTED] Pickup: 16 SCU Diamond -> Other Location

Stop 2: Location Name (2 missions to accept)
  [PLANNED] Delivery: 24 SCU Distilled Spirits
  [PLANNED] Pickup: 32 SCU Ship Ammunition -> Somewhere

Stop 3: Location Name
  [ACCEPTED] Delivery: 16 SCU Diamond
```

---

## Persistence Format (`planned_route.json`)

```json
{
  "version": "1.0",
  "started_at": "2025-12-06T10:30:00Z",
  "stops": [
    {
      "location": "Baijini Point",
      "stop_number": 1,
      "pickups": [...],
      "deliveries": [...]
    }
  ],
  "mission_scans": [...],
  "accepted_objective_ids": ["obj-uuid-1", "obj-uuid-2"]
}
```
