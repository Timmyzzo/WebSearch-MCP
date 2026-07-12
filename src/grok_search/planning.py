import uuid

from pydantic import BaseModel

PHASE_NAMES = [
    "intent_analysis",
    "complexity_assessment",
    "query_decomposition",
    "search_strategy",
    "tool_selection",
    "execution_order",
]

REQUIRED_PHASES: dict[int, set[str]] = {
    1: {"intent_analysis", "complexity_assessment", "query_decomposition"},
    2: {
        "intent_analysis",
        "complexity_assessment",
        "query_decomposition",
        "search_strategy",
        "tool_selection",
    },
    3: set(PHASE_NAMES),
}

_ACCUMULATIVE_LIST_PHASES = {"query_decomposition", "tool_selection"}
_MERGE_STRATEGY_PHASE = "search_strategy"


def _split_csv(value: str) -> list[str]:
    return [s.strip() for s in value.split(",") if s.strip()] if value else []


class PhaseRecord(BaseModel):
    phase: str
    thought: str
    data: dict | list | None = None
    confidence: float = 1.0


class PlanningSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.phases: dict[str, PhaseRecord] = {}
        self.complexity_level: int | None = None

    @property
    def completed_phases(self) -> list[str]:
        return [p for p in PHASE_NAMES if p in self.phases]

    def required_phases(self) -> set[str]:
        return REQUIRED_PHASES.get(self.complexity_level or 3, REQUIRED_PHASES[3])

    def is_complete(self) -> bool:
        if self.complexity_level is None:
            return False
        return self.required_phases().issubset(self.phases.keys())

    def build_executable_plan(self) -> dict:
        return {name: record.data for name, record in self.phases.items()}


class PlanningEngine:
    def __init__(self):
        self._sessions: dict[str, PlanningSession] = {}

    def get_session(self, session_id: str) -> PlanningSession | None:
        return self._sessions.get(session_id)

    def process_phase(
        self,
        phase: str,
        thought: str,
        session_id: str = "",
        is_revision: bool = False,
        revises_phase: str = "",
        confidence: float = 1.0,
        phase_data: dict | list | None = None,
    ) -> dict:
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
        else:
            sid = session_id if session_id else uuid.uuid4().hex[:12]
            session = PlanningSession(sid)
            self._sessions[sid] = session

        target = revises_phase if is_revision and revises_phase else phase
        if target not in PHASE_NAMES:
            return {"error": f"Unknown phase: {target}. Valid: {', '.join(PHASE_NAMES)}"}

        if target in _ACCUMULATIVE_LIST_PHASES:
            if is_revision:
                session.phases[target] = PhaseRecord(
                    phase=target,
                    thought=thought,
                    data=[phase_data] if not isinstance(phase_data, list) else phase_data,
                    confidence=confidence,
                )
            elif target in session.phases and isinstance(session.phases[target].data, list):
                session.phases[target].data.append(phase_data)
                session.phases[target].thought = thought
                session.phases[target].confidence = confidence
            else:
                session.phases[target] = PhaseRecord(
                    phase=target,
                    thought=thought,
                    data=[phase_data],
                    confidence=confidence,
                )
        elif target == _MERGE_STRATEGY_PHASE:
            existing = session.phases.get(target)
            if is_revision:
                session.phases[target] = PhaseRecord(
                    phase=target,
                    thought=thought,
                    data=phase_data,
                    confidence=confidence,
                )
            elif existing and isinstance(existing.data, dict) and isinstance(phase_data, dict):
                existing.data.setdefault("search_terms", []).extend(
                    phase_data.get("search_terms", [])
                )
                if phase_data.get("approach"):
                    existing.data["approach"] = phase_data["approach"]
                if phase_data.get("fallback_plan"):
                    existing.data["fallback_plan"] = phase_data["fallback_plan"]
                existing.thought = thought
                existing.confidence = confidence
            else:
                session.phases[target] = PhaseRecord(
                    phase=target,
                    thought=thought,
                    data=phase_data,
                    confidence=confidence,
                )
        else:
            session.phases[target] = PhaseRecord(
                phase=target,
                thought=thought,
                data=phase_data,
                confidence=confidence,
            )

        if target == "complexity_assessment" and isinstance(phase_data, dict):
            level = phase_data.get("level")
            if level in (1, 2, 3):
                session.complexity_level = level

        complete = session.is_complete()
        result: dict = {
            "session_id": session.session_id,
            "completed_phases": session.completed_phases,
            "complexity_level": session.complexity_level,
            "plan_complete": complete,
        }

        remaining = [
            p for p in PHASE_NAMES if p in session.required_phases() and p not in session.phases
        ]
        if remaining:
            result["phases_remaining"] = remaining

        if complete:
            result["executable_plan"] = session.build_executable_plan()

        return result


engine = PlanningEngine()
