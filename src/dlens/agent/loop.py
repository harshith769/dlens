"""The agent loop: a tool phase, then an answer phase rebuilt from the ledger.

Call budget: at most ``MAX_LLM_CALLS`` (8) LLM calls per question, counting every call. The tool
phase may use ``MAX_TOOL_PHASE_CALLS`` (5) of them, so the answer call, one answer repair and the
validator's "regenerate once" always fit. Tool calls made by code (chain mode) are not
LLM calls.

Token budget: every call is measured with ``estimate_tokens`` against ``client.max_input_tokens``
before it is sent. The tool phase compacts older tool messages (``context.fit``) and stops when
even that cannot fit. The answer prompt is rebuilt from the Toolbox log, never from history, and
is trimmed (``partial_evidence``) if it does not fit.
"""

from __future__ import annotations

import difflib
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dlens.agent import prompts
from dlens.agent.answer import DRAFT_SCHEMA, Answer, AnswerDraft, Clarification, attach
from dlens.agent.context import History, fit
from dlens.agent.evidence import (
    EvidenceItem,
    build_evidence,
    render_evidence,
    tool_errors,
    trim,
)
from dlens.agent.llm.base import LLMClient
from dlens.agent.llm.ollama import strip_think
from dlens.agent.llm.tokens import estimate_tokens
from dlens.agent.llm.types import (
    InputTooLarge,
    LLMResponse,
    Message,
    ProviderError,
    QuotaExceeded,
    ToolCall,
    ToolSpec,
)
from dlens.agent.runlog import RunLogger, RunRecord, Step, StepResult, now_iso
from dlens.agent.tools import Toolbox, ToolResult
from dlens.agent.tools.entity import AMBIGUOUS_GAP
from dlens.agent.validator import ValidationResult, salvage, validate
from dlens.lineage import column_id, short_id

MAX_LLM_CALLS = 8
MAX_TOOL_PHASE_CALLS = 5
MAX_DUPLICATE_TURNS = 2
REPAIR_ECHO_CHARS = 600
REPAIR_ERROR_CHARS = 300
REGENERATE_LIST_TOKENS = 300

_TOOL_NAMES = "resolve_entity|trace_upstream|impact_downstream|get_model_sql"
_TEXT_TOOL_CALL = re.compile(rf'<tool_call>|\{{\s*"name"\s*:\s*"({_TOOL_NAMES})"')
_QUESTION_COLUMN = re.compile(r"(?<![\w.])[A-Za-z_]\w*\.[A-Za-z_]\w*(?![\w.])")
_IMPACT_WORDING = re.compile(r"\b(affect|impact|chang|break|downstream)\w*", re.IGNORECASE)
_REACH_WORDING = re.compile(r"\b(affect|impact|depend|feed|flow|reach|chang)\w*", re.IGNORECASE)
_DEPEND_WORDING = re.compile(r"\bdepend\w*", re.IGNORECASE)
_FILE_SUFFIXES = {"sql", "csv", "yml", "yaml", "md", "py", "json", "txt"}
MAX_CODE_EVIDENCE_COLUMNS = 2
UNKNOWN_COLUMN_SUGGESTIONS = 3
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class _Refuse(Exception):
    """Stop the run and return a refused answer with this reason."""


@dataclass
class AgentRun:
    answer: Answer
    record: RunRecord
    log_path: Path | None = None


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        v = value.strip().lower()
        if v.lstrip("-").isdigit():
            return int(v)
        if v in ("true", "false"):
            return v == "true"
        return v
    return value


_DEFAULTS: dict[str, dict[str, Any]] = {
    "resolve_entity": {"k": 5},
    "trace_upstream": {"max_depth": 10, "include_indirect": False},
    "impact_downstream": {"max_depth": 10, "include_indirect": True},
    "get_model_sql": {"around_column": None},
}


class Agent:
    def __init__(
        self,
        client: LLMClient,
        toolbox: Toolbox,
        logger: RunLogger | None = None,
        project: str = "",
    ) -> None:
        self.client = client
        self.toolbox = toolbox
        self.logger = logger
        self.project = project
        self.specs: list[ToolSpec] = toolbox.specs()

    # -- public ----------------------------------------------------------------------------

    def ask(self, question: str) -> AgentRun:
        self.toolbox.reset()
        prov = self.client.provider
        self.record = RunRecord(
            run_id=uuid.uuid4().hex,
            started_at=now_iso(),
            question=question,
            project=self.project,
            provider=prov.name,
            model=prov.model,
            params=dict(prov.params),
        )
        t0 = time.perf_counter()
        try:
            answer = self._run(question, t0)
        except _Refuse as e:
            answer = Answer.refusal(str(e))
            self.record.error = str(e)
        except (ProviderError, QuotaExceeded, InputTooLarge) as e:
            reason = f"{type(e).__name__}: {e}"
            answer = Answer.refusal(reason)
            self.record.error = reason
        self.record.timings["total_ms"] = _ms(t0)
        self.record.final_answer = answer.model_dump(mode="json")
        self._totals()
        path = self.logger.write(self.record) if self.logger else None
        return AgentRun(answer=answer, record=self.record, log_path=path)

    # -- phases ----------------------------------------------------------------------------

    def _run(self, question: str, t0: float) -> Answer:
        unknown = self._unknown_column(question)
        if unknown is not None:
            self.record.stop_reason = "unknown_column"
            raise _Refuse(unknown)
        self._tool_phase(question)
        if not any(i.startswith(("e_", "s_")) for i in self.toolbox.emitted_ids):
            self._code_evidence(question)
        self._reachability_fact(question)
        self.record.timings["tool_ms"] = _ms(t0)

        directives: list[str] = []
        amb = self._ambiguity(question)
        if amb is not None:
            self.record.ambiguity = amb
            if amb["mode"] == "clarification":
                clar = Clarification(
                    question=prompts.clarification_question(amb["query"]),
                    candidates=amb["candidates"],
                )
                self.record.clarification = clar.model_dump()
                return Answer(answer_text=clar.question, clarification=clar)
            if amb["mode"] == "chain":
                directives.append(prompts.chain_directive(amb["candidates"], amb["downstream"]))
            else:
                directives.append(prompts.per_candidate_directive(amb["candidates"]))

        t1 = time.perf_counter()
        answer = self._answer_phase(question, directives)
        self.record.timings["answer_ms"] = _ms(t1)
        return answer

    def _tool_phase(self, question: str) -> None:
        history = History(
            [
                Message(role="system", content=prompts.TOOL_SYSTEM),
                Message(role="user", content=question),
            ]
        )
        seen: dict[str, tuple[int, int]] = {}  # canonical call -> (log index, message index)
        duplicate_turns = 0
        repaired = False
        phase = "tool"
        while True:
            if self.record.llm_calls >= MAX_TOOL_PHASE_CALLS:
                self.record.stop_reason = "step_cap"
                return
            ok, compactions = fit(
                history, self.specs, self.client.max_input_tokens, len(self.record.steps)
            )
            self.record.compactions += compactions
            if not ok:
                self.record.stop_reason = "budget"
                return
            try:
                resp, step = self._llm(history.messages, self.specs, None, phase)
            except ProviderError as e:
                if "tool call" not in str(e).lower():
                    raise
                if repaired:
                    raise _Refuse(f"malformed tool call: {e}") from e
                repaired, phase = True, "repair"
                history.messages.append(
                    Message(role="user", content=prompts.TOOL_REPAIR.format(error=_clip(str(e))))
                )
                continue
            phase = "tool"
            text = strip_think(resp.text)
            if not resp.tool_calls:
                if _TEXT_TOOL_CALL.search(text):
                    if repaired:
                        raise _Refuse("malformed tool call: the model wrote a call as text twice")
                    repaired, phase = True, "repair"
                    history.messages += [
                        Message(role="assistant", content=_clip(text, REPAIR_ECHO_CHARS)),
                        Message(
                            role="user",
                            content=prompts.TOOL_REPAIR.format(error="written as text"),
                        ),
                    ]
                    continue
                self.record.stop_reason = "model_done"
                return
            history.messages.append(resp.as_message().model_copy(update={"content": text}))
            all_duplicates = True
            for tc in resp.tool_calls:
                key = self._canonical(tc)
                if key in seen:
                    log_idx, msg_idx = seen[key]
                    earlier = self.toolbox.log[log_idx]
                    history.add_tool(earlier, tc.id, history.messages[msg_idx].content)
                    history.levels[len(history.messages) - 1] = history.levels[msg_idx]
                    step.results.append(_step_result(earlier, deduped=True, duplicate_of=log_idx))
                    continue
                all_duplicates = False
                result = self.toolbox.call(tc.name, tc.arguments)
                seen[key] = (len(self.toolbox.log) - 1, len(history.messages))
                history.add_tool(result, tc.id)
                step.results.append(_step_result(result))
            duplicate_turns = duplicate_turns + 1 if all_duplicates else 0
            if duplicate_turns >= MAX_DUPLICATE_TURNS:
                self.record.stop_reason = "repeating"
                return

    def _answer_phase(self, question: str, directives: list[str]) -> Answer:
        items = build_evidence(self.toolbox)
        if not any(it.id for it in items):
            errors = tool_errors(self.toolbox)
            reason = "no lineage evidence was found for this question"
            if errors:
                reason += ": " + "; ".join(errors[:3])
            raise _Refuse(reason)

        cap = self.client.max_input_tokens

        def messages(its: list[EvidenceItem], extra: list[str]) -> list[Message]:
            user = prompts.answer_user(question, render_evidence(its), directives + extra)
            return [
                Message(role="system", content=prompts.ANSWER_SYSTEM),
                Message(role="user", content=user),
            ]

        def tokens(its: list[EvidenceItem], extra: list[str]) -> int:
            return estimate_tokens(messages(its, extra), None, DRAFT_SCHEMA)

        partial: list[str] = []
        dropped: list[str] = []
        if tokens(items, []) > cap:
            partial = [prompts.PARTIAL_DIRECTIVE]
            before = tokens(items, partial)
            items, dropped = trim(items, lambda its: tokens(its, partial) <= cap)
            self.record.compactions.append(
                {
                    "step": len(self.record.steps),
                    "phase": "answer",
                    "dropped_ids": dropped,
                    "tokens_before": before,
                    "tokens_after": tokens(items, partial),
                }
            )
            if not any(it.id for it in items):
                raise _Refuse("the evidence does not fit in the input-token budget")
        self.record.evidence = {
            "ids": [it.id for it in items if it.id],
            "dropped_ids": dropped,
            "partial_evidence": bool(partial),
        }

        msgs = messages(items, partial)
        resp, _ = self._llm(msgs, None, DRAFT_SCHEMA, "answer")
        self.record.draft_raw = resp.text
        try:
            draft = _parse_draft(resp.text)
        except ValidationError as e:
            error = _clip(_one_line(e), REPAIR_ERROR_CHARS)
            repair = [
                *msgs,
                Message(role="assistant", content=_clip(resp.text, REPAIR_ECHO_CHARS)),
                Message(role="user", content=prompts.ANSWER_REPAIR.format(error=error)),
            ]
            if estimate_tokens(repair, None, DRAFT_SCHEMA) > cap:
                repair = [*msgs, repair[-1]]
            resp, _ = self._llm(repair, None, DRAFT_SCHEMA, "repair")
            self.record.draft_raw = resp.text
            try:
                draft = _parse_draft(resp.text)
            except ValidationError as e2:
                raise _Refuse(f"invalid answer JSON: {_clip(_one_line(e2))}") from e2
        self.record.draft = draft.model_dump(mode="json")

        answer = attach(draft, self.toolbox, partial_evidence=bool(partial))
        return self._validate(question, msgs, answer, bool(partial))

    # -- validation: validate -> regenerate once -> salvage ----------------------------------

    def _validate(
        self, question: str, msgs: list[Message], answer: Answer, partial: bool
    ) -> Answer:
        first = validate(answer, self.toolbox, question)
        v: dict[str, Any] = {
            "passed": first.passed,
            "regenerated": False,
            "warning": False,
            "counts": first.counts,  # draft failures by rule
            "repairs": first.repairs,
            "completions": first.completions,  # R8c, reported separately like repairs
            "dropped_claims": [],
            "skipped": first.skipped,  # refused / clarification: not checked
            "first": _summary(first),
            "second": None,
        }
        self.record.validation = v
        if first.passed:
            return first.cleaned_answer

        second: ValidationResult | None = None
        if self.record.llm_calls < MAX_LLM_CALLS:  # the budget reserves this call
            v["regenerated"] = True
            second = self._regenerate(question, msgs, first, partial)
            if second is not None:
                v["second"] = _summary(second)
                if second.passed:
                    v.update(passed=True, repairs=second.repairs, completions=second.completions)
                    out = second.cleaned_answer
                    return out

        # Still failing (or no call left): keep only passing claims, with a warning.
        rounds = [r for r in (second, first) if r is not None]  # ties go to the second
        best = max(rounds, key=lambda r: len(r.cleaned_answer.claims) - len(r.dropped_claims))
        v.update(
            passed=False,
            warning=True,
            repairs=best.repairs,
            completions=best.completions,
            dropped_claims=best.dropped_claims,
        )
        salvaged = salvage(best, self.toolbox)
        if salvaged is None:
            # Refused BY THE VALIDATOR: the warning flag tells render() (CLI, UI) to say so.
            reason = "no verifiable claims: every claim failed validation"
            self.record.error = reason
            return Answer.refusal(reason).model_copy(update={"validation_warning": True})
        return salvaged

    def _regenerate(
        self, question: str, msgs: list[Message], failed: ValidationResult, partial: bool
    ) -> ValidationResult | None:
        """One more answer call listing what failed. None if the reply is not valid JSON."""
        lines = [
            f"- {'answer_text' if f.claim_index is None else f'claim {f.claim_index}'}: "
            f"{f.rule} {f.item_id or ''}: {_clip(f.message, 100)}"
            for f in failed.failures
        ]
        if failed.fact is not None and any(f.rule == "R9" for f in failed.failures):
            # first, so trimming the list never drops it; the fact is not clipped
            fact = failed.fact
            lines.insert(0, f"- The graph check says: {fact['fact_id']}: {fact['fact']}")
        cap = self.client.max_input_tokens

        def build(n: int) -> list[Message]:
            text = prompts.REGENERATE.format(failures="\n".join(lines[:n]))
            return [*msgs, Message(role="user", content=text)]

        n = len(lines)
        while n > 1 and (
            estimate_tokens([build(n)[-1]]) > REGENERATE_LIST_TOKENS
            or estimate_tokens(build(n), None, DRAFT_SCHEMA) > cap
        ):
            n -= 1
        resp, _ = self._llm(build(n), None, DRAFT_SCHEMA, "regenerate")
        self.record.regenerate_draft_raw = resp.text
        try:
            draft = _parse_draft(resp.text)
        except ValidationError:
            return None
        answer = attach(draft, self.toolbox, partial_evidence=partial)
        return validate(answer, self.toolbox, question)

    # -- ambiguity policy --------------------------------------------------------------------

    def _ambiguity(self, question: str) -> dict[str, Any] | None:
        """Decide chain / per-candidate / clarification for the first ambiguous resolve_entity
        result that the question does not itself disambiguate."""
        g = self.toolbox.graph
        q = question.lower()
        for r in list(self.toolbox.log):
            p = r.llm_payload
            if r.tool != "resolve_entity" or r.is_error or not p.get("ambiguous"):
                continue
            cands = p["candidates"]
            top = cands[0]["score"]
            tie = [c for c in cands if c["score"] >= top - AMBIGUOUS_GAP - 1e-9]
            names = [c["id"] for c in tie]
            if _named_once(q, names):
                continue
            base = {"query": p.get("query", ""), "candidates": names}
            columns = [c for c in tie if c["kind"] == "column"]
            downstream = self._chain_end(names) if len(columns) == len(tie) else None
            if downstream is not None:
                self._ensure_traced(downstream)
                return {**base, "mode": "chain", "downstream": g.display_name(downstream)}
            if len(tie) <= 3:
                return {**base, "mode": "per_candidate"}
            return {**base, "mode": "clarification"}
        return None

    def _chain_end(self, names: list[str]) -> str | None:
        """The most downstream column if all ``names`` lie on one lineage chain, else None."""
        g = self.toolbox.graph
        try:
            cols = [g.resolve(n) for n in names]
        except Exception:
            return None
        ups = {
            c: {e.from_column for path in g.upstream(c, max_depth=50) for e in path.edges}
            for c in cols
        }
        for i, a in enumerate(cols):
            for b in cols[i + 1 :]:
                if a not in ups[b] and b not in ups[a]:
                    return None
        ends = [c for c in cols if all(o in ups[c] for o in cols if o != c)]
        return ends[0] if ends else None

    def _unknown_column(self, question: str) -> str | None:
        """A dotted ``model.column`` in the question whose model (or seed, or source) exists but
        whose column does not: the refusal reason, with up to 3 of that model's closest columns.
        CTE aliases are never refused, because they are not node names in the graph."""
        g = self.toolbox.graph
        by_name: dict[str, list[str]] = {}
        for uid in g.model_ids():
            by_name.setdefault((g.model_info(uid) or {}).get("name", "").lower(), []).append(uid)
        for m in _QUESTION_COLUMN.finditer(question):
            model, col = m.group(0).lower().split(".")
            uids = by_name.get(model)
            if not uids or col in _FILE_SUFFIXES:
                continue
            if any(g.has_column(column_id(u, col)) for u in uids):
                continue
            real = sorted(
                {g.nx_graph.nodes[c]["name"] for c in g.columns() if g.model_of(c) in uids}
            )
            close = difflib.get_close_matches(col, real, n=UNKNOWN_COLUMN_SUGGESTIONS, cutoff=0.0)
            reason = f"{model} has no column {col}"
            return reason + (f" (closest: {', '.join(close)})" if close else "")
        return None

    def _code_evidence(self, question: str) -> None:
        """Nothing citable was emitted. If the question names exact, existing ``model.column``
        ids, code runs the fitting tool on each (at most 2): ``impact_downstream`` when the
        wording is about effects (affect / impact / change / break / downstream), else
        ``trace_upstream``. "code" steps, not LLM calls. Calls the log already has are skipped."""
        g = self.toolbox.graph
        tool = "impact_downstream" if _IMPACT_WORDING.search(question) else "trace_upstream"
        names = self._question_columns(question)
        for name in names[:MAX_CODE_EVIDENCE_COLUMNS]:
            if not self._already_called(tool, g.resolve(name)):
                self._code_call(tool, {"column_id": name})
        if names:
            self.record.stop_reason += "+code_evidence"

    def _question_columns(self, question: str) -> list[str]:
        """Distinct exact, existing ``model.column`` ids the question names, in order."""
        g = self.toolbox.graph
        names: list[str] = []
        for m in _QUESTION_COLUMN.finditer(question):
            text = m.group(0).lower()
            try:
                column = g.resolve(text)
            except Exception:
                continue
            if g.display_name(column).lower() != text and short_id(column) != text:
                continue
            name = g.display_name(column)
            if name not in names:
                names.append(name)
        return names

    def _reachability_fact(self, question: str) -> None:
        """A yes/no reachability question (exactly 2 exact columns named, plus affect / impact /
        depend / feed / flow / reach / change wording) gets a code-made ``r_`` fact: does the
        first-named column reach the second? "depend" asks the reverse ("does Y depend on X":
        X -> Y). The validator's R9 holds the answer's verdict to this fact."""
        names = self._question_columns(question)
        if len(names) != 2 or not _REACH_WORDING.search(question):
            return
        src, dst = names[::-1] if _DEPEND_WORDING.search(question) else names
        self._code_call("reachability", {"from_column": src, "to_column": dst})

    def _already_called(self, tool: str, column: str) -> bool:
        return any(
            r.tool == tool and not r.is_error and r.side_records.get("column") == column
            for r in self.toolbox.log
        )

    def _code_call(self, tool: str, args: dict[str, Any]) -> None:
        result = self.toolbox.call(tool, args, code=True)
        self.record.steps.append(
            Step(
                index=len(self.record.steps),
                phase="code",
                tool_calls=[{"name": tool, "arguments": args}],
                results=[_step_result(result)],
            )
        )

    def _ensure_traced(self, column: str) -> None:
        for r in self.toolbox.log:
            if r.tool == "trace_upstream" and r.side_records.get("column") == column:
                return
        self._code_call("trace_upstream", {"column_id": self.toolbox.graph.display_name(column)})

    # -- helpers -----------------------------------------------------------------------------

    def _canonical(self, tc: ToolCall) -> str:
        args = {**_DEFAULTS.get(tc.name, {}), **{k: _norm(v) for k, v in tc.arguments.items()}}
        if tc.name in ("trace_upstream", "impact_downstream") and isinstance(
            args.get("column_id"), str
        ):
            try:
                args["column_id"] = self.toolbox.graph.resolve(args["column_id"])
            except Exception:
                pass
        return f"{tc.name}:{sorted(args.items(), key=lambda kv: kv[0])!r}"

    def _llm(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        schema: dict[str, Any] | None,
        phase: str,
    ) -> tuple[LLMResponse, Step]:
        """One LLM call (plus one retry on a retryable provider error), recorded as a step."""
        for attempt in (0, 1):
            if self.record.llm_calls >= MAX_LLM_CALLS:
                raise _Refuse(f"LLM call budget of {MAX_LLM_CALLS} per question used up")
            step = Step(
                index=len(self.record.steps),
                phase=phase,  # type: ignore[arg-type]
                est_input_tokens=estimate_tokens(messages, tools, schema),
            )
            self.record.steps.append(step)
            t = time.perf_counter()
            try:
                resp = self.client.chat(messages, tools, schema)
            except ProviderError as e:
                step.error = str(e)
                step.latency_ms = _ms(t)
                if e.retryable and attempt == 0:
                    continue
                raise
            except Exception as e:  # QuotaExceeded, InputTooLarge: logged, then handled by ask()
                step.error = f"{type(e).__name__}: {e}"
                raise
            step.latency_ms = _ms(t)
            step.cached = resp.cached
            step.input_tokens = resp.usage.input_tokens
            step.output_tokens = resp.usage.output_tokens
            step.text = resp.text
            step.tool_calls = [c.model_dump(mode="json") for c in resp.tool_calls]
            return resp, step
        raise AssertionError("unreachable")

    def _totals(self) -> None:
        llm = [s for s in self.record.steps if s.is_llm_call]
        self.record.tokens = {
            "max_est_input": max((s.est_input_tokens for s in llm), default=0),
            "sum_input": sum(s.input_tokens for s in llm),
            "sum_output": sum(s.output_tokens for s in llm),
            "llm_calls": len(llm),
            "cached_calls": sum(s.cached for s in llm),
        }


def ask(
    question: str,
    client: LLMClient,
    toolbox: Toolbox,
    logger: RunLogger | None = None,
    project: str = "",
) -> AgentRun:
    return Agent(client, toolbox, logger, project).ask(question)


def _named_once(question: str, names: list[str]) -> bool:
    """The question picks exactly one candidate: by its full id, or by a model name only it has."""
    full = [n for n in names if re.search(rf"(?<![\w.]){re.escape(n.lower())}(?!\w)", question)]
    if len(full) == 1:
        return True
    by_model = [
        n
        for n in names
        if "." in n
        and re.search(rf"(?<![\w.]){re.escape(n.rsplit('.', 1)[0].lower())}(?!\w)", question)
    ]
    return len(by_model) == 1


def _summary(r: ValidationResult) -> dict[str, Any]:
    return {
        "passed": r.passed,
        "failures": [f.model_dump() for f in r.failures],
        "repairs": r.repairs,
        "completions": r.completions,
        "dropped_claims": r.dropped_claims,
        "counts": r.counts,
        "claims": len(r.cleaned_answer.claims),
    }


def _parse_draft(text: str) -> AnswerDraft:
    return AnswerDraft.model_validate_json(_FENCE.sub("", text.strip()) or "{}")


def _step_result(
    r: ToolResult, deduped: bool = False, duplicate_of: int | None = None
) -> StepResult:
    return StepResult(
        tool=r.tool,
        args=r.args,
        llm_payload=r.llm_payload,
        side_records=r.side_records,
        deduped=deduped,
        duplicate_of=duplicate_of,
    )


def _clip(text: str, n: int = REPAIR_ERROR_CHARS) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _one_line(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, x['loc'])) or 'json'}: {x['msg']}" for x in e.errors())


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)
