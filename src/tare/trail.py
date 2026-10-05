"""Trail: one neutral record of a run, the same for every agent (epic Swap).

A trail is the task, the agent's messages, its tool calls and their results. Each adapter
translates its own session format into it; one renderer turns a trail prefix into a
handoff prompt that any agent can continue from. A new agent needs a snapshot hook, a
translation into the trail and a way to start a session with a prompt; capsules, tails,
Cliff and Swap come with it.
"""
import json
from dataclasses import dataclass, field

SHORT = 600  # characters kept of a tool's input or output in a handoff


@dataclass
class Event:
    kind: str  # say, call, result
    text: str
    tool: str = ""


@dataclass
class Step:
    """One model tool call (or several issued together) and where it ends."""
    ids: list[str]  # the ids the snapshot hook saw for this step, in order
    trail_cut: int  # events of the trail up to and including this step's results
    native_cut: int | None  # lines of the native session up to this step (native resume), if any
    tool: str  # what the step did, for reports


@dataclass
class Trail:
    events: list[Event] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)


def _short(text: str) -> str:
    text = text.strip()
    return text if len(text) <= SHORT else text[:SHORT] + f" … [{len(text) - SHORT} more characters]"


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return "" if content is None else json.dumps(content)


def claude(lines: list[str]) -> Trail:
    """Claude Code session transcript (JSON lines) to a trail."""
    trail = Trail()
    calls: dict[int, list[str]] = {}  # transcript line of an assistant message -> its tool ids
    origin: dict[str, int] = {}
    described: dict[str, str] = {}
    waiting: dict[int, set[str]] = {}
    for i, line in enumerate(lines):
        message = json.loads(line).get("message") or {}
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            kind = block.get("type")
            if kind == "text" and message.get("role") == "assistant" and block.get("text", "").strip():
                trail.events.append(Event("say", block["text"].strip()))
            elif kind == "tool_use":
                arguments = block.get("input", {})
                detail = str(arguments.get("command") or arguments.get("file_path") or json.dumps(arguments))
                trail.events.append(Event("call", _short(detail), block.get("name", "?")))
                calls.setdefault(i, []).append(block["id"])
                origin[block["id"]] = i
                described[block["id"]] = f"{block.get('name', '?')} {detail.splitlines()[0][:70] if detail else ''}".strip()
                waiting.setdefault(i, set()).add(block["id"])
            elif kind == "tool_result":
                trail.events.append(Event("result", _short(_text(block.get("content")))))
                made = origin.get(block.get("tool_use_id"))
                if made is None:
                    continue
                waiting[made].discard(block["tool_use_id"])
                if not waiting[made]:  # every call of that message has its result: the step ends here
                    ids = calls[made]
                    trail.steps.append(Step(ids, len(trail.events), i + 1, " + ".join(described[t] for t in ids)))
    return trail


def codex(lines: list[str]) -> Trail:
    """Codex rollout (JSON lines) to a trail. In code mode one model call (`exec`) runs several
    commands; the snapshot hook sees the commands, so a step carries their ids."""
    trail = Trail()
    calls: dict[str, dict] = {}  # call_id -> {"inner": [...], "tool": ...}
    current: str | None = None
    for i, line in enumerate(lines):
        entry = json.loads(line)
        payload = entry.get("payload") or {}
        kind = entry.get("type")
        if kind == "response_item":
            item = payload.get("type")
            if item == "message" and payload.get("role") == "assistant":
                text = _text(payload.get("content")).strip()
                if text:
                    trail.events.append(Event("say", text))
            elif item in ("custom_tool_call", "function_call"):
                detail = payload.get("input") or payload.get("arguments") or ""
                name = payload.get("name", "?")
                trail.events.append(Event("call", _short(str(detail)), name))
                current = payload["call_id"]
                first = str(detail).strip().splitlines()[0][:70] if str(detail).strip() else ""
                calls[current] = {"inner": [current], "tool": f"{name} {first}".strip()}
            elif item in ("custom_tool_call_output", "function_call_output"):
                trail.events.append(Event("result", _short(_text(payload.get("output")))))
                call = calls.get(payload.get("call_id"))
                if call:
                    trail.steps.append(Step(call["inner"], len(trail.events), i + 1, call["tool"]))
                current = None
        elif kind == "event_msg" and payload.get("type") == "item_completed" and current:
            item = payload.get("item") or {}
            if item.get("type") == "CommandExecution" and item.get("id"):
                calls[current]["inner"].append(item["id"])
    return trail


def pi(lines: list[str]) -> Trail:
    """Pi session (JSON lines, a tree of message entries) to a trail."""
    trail = Trail()
    calls: dict[int, list[str]] = {}
    origin: dict[str, int] = {}
    described: dict[str, str] = {}
    waiting: dict[int, set[str]] = {}
    for i, line in enumerate(lines):
        entry = json.loads(line)
        if entry.get("type") != "message":
            continue
        message = entry.get("message") or {}
        role = message.get("role")
        if role == "assistant":
            for block in message.get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    trail.events.append(Event("say", block["text"].strip()))
                elif block.get("type") == "toolCall":
                    arguments = block.get("arguments") or {}
                    detail = str(arguments.get("command") or arguments.get("path") or json.dumps(arguments))
                    trail.events.append(Event("call", _short(detail), block.get("name", "?")))
                    calls.setdefault(i, []).append(block["id"])
                    origin[block["id"]] = i
                    described[block["id"]] = f"{block.get('name', '?')} {detail.splitlines()[0][:70] if detail else ''}".strip()
                    waiting.setdefault(i, set()).add(block["id"])
        elif role == "toolResult":
            trail.events.append(Event("result", _short(_text(message.get("content")))))
            made = origin.get(message.get("toolCallId"))
            if made is None:
                continue
            waiting[made].discard(message["toolCallId"])
            if not waiting[made]:
                ids = calls[made]
                trail.steps.append(Step(ids, len(trail.events), i + 1, " + ".join(described[t] for t in ids)))
    return trail


def render(task: str, events: list[Event], workspace_only: bool = False) -> str:
    """The handoff prompt: the task and what happened so far, the same for every agent."""
    head = ("You are taking over a task in /work. The workspace is exactly as the previous session "
            "left it.\n\nThe task:\n" + task.strip() + "\n")
    if workspace_only or not events:
        return head + "\nContinue from the current state of the workspace and finish the task."
    lines = []
    for n, event in enumerate(events, 1):
        if event.kind == "say":
            lines.append(f"{n}. The agent said: {event.text}")
        elif event.kind == "call":
            lines.append(f"{n}. The agent called {event.tool}: {event.text}")
        else:
            lines.append(f"{n}. Result: {event.text}")
    return (head + "\nWhat happened so far (long inputs and outputs are shortened):\n" + "\n".join(lines)
            + "\n\nContinue from here and finish the task.")
