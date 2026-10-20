#!/usr/bin/env python3
"""Read-only paper ledger audit. Python 3.9+, standard library only."""

import argparse
import hashlib
import json
import math
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote, urlsplit


CHECKS = (
    "chapter_overviews", "model_scenario_consistency",
    "method_implementation_mapping", "flowchart_and_equations",
    "fair_comparison", "tense_review", "cross_references",
)
PROPERTIES = {"robustness", "convergence", "stability"}
INNOVATION_DIMENSIONS = {"object", "scenario", "method"}
NARRATIVE_MODES = {"scenario", "method"}
DEFAULT_REQUIREMENTS = {
    "min_references": 40, "self_citations": [6, 7], "min_proved_properties": 1,
}
DECIMAL_LITERAL = r"[+\-−]?(?:\d+(?:\.\d*)?|\.\d+)"
NUMBER_LITERAL = DECIMAL_LITERAL + r"(?:[eE][+\-]?\d+)?"
MATH_SPACE = r"(?:\s|\\[,;:!]|\\(?:qquad|quad)\b)*"
LATEX_SCIENTIFIC = re.compile(
    rf"(?<![\d.])(?P<mantissa>{DECIMAL_LITERAL}){MATH_SPACE}(?:\\times|\\cdot|×|·)"
    rf"{MATH_SPACE}10{MATH_SPACE}\^{MATH_SPACE}"
    r"(?:\{\s*(?P<braced>[+\-−]?\d+)\s*\}|(?P<bare>[+\-−]?\d+))"
)
DOI_LITERAL = re.compile(r"10\.\d{4,9}/\S+")
HASH_CHUNK_SIZE = 1024 * 1024


class SchemaError(ValueError):
    pass


def finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def number_text(value):
    """Parse the literal precision used in the manuscript, without units."""
    try:
        if not re.fullmatch(NUMBER_LITERAL, value):
            raise ValueError("需使用十进制或科学计数法，不带单位")
        decimal = Decimal(value.replace("−", "-"))
        exponent = decimal.as_tuple().exponent
        if not decimal.is_finite() or not -324 <= exponent <= 308:
            raise ValueError("数字精度或范围超出支持范围")
        parsed = float(decimal)
        quantum = float(Decimal(1).scaleb(exponent))
        if not finite_number(parsed) or not finite_number(quantum):
            raise ValueError("数字超出有限浮点范围")
        return parsed, quantum / 2
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise SchemaError(f"报告数字文本无效 {value!r}: {exc}") from exc


def matches_report(expected, literal):
    reported, rounding = number_text(literal)
    floating = max(abs(expected), abs(reported), 1e-300) * 1e-12
    return abs(expected - reported) <= rounding + floating


def number_in_quote(quote, literal):
    """Match whole numbers, including TeX scientific notation, at recorded precision."""
    def scientific(match):
        exponent = match["braced"] or match["bare"]
        return f"{match['mantissa']}e{exponent}".replace("−", "-")

    normalized = LATEX_SCIENTIFIC.sub(scientific, quote)
    target = Decimal(literal.replace("−", "-"))
    precision = target.as_tuple().exponent
    for match in re.finditer(NUMBER_LITERAL, normalized):
        try:
            candidate = Decimal(match[0].replace("−", "-"))
            if candidate == target and candidate.as_tuple().exponent == precision:
                return True
        except InvalidOperation:
            continue
    return False


def source_locator_key(locator):
    """Normalize DOI aliases and URL hosts; preserve case-sensitive paths and queries."""
    value = locator.strip()
    doi = value[4:].strip() if value[:4].casefold() == "doi:" else value
    if DOI_LITERAL.fullmatch(doi):
        return ("doi", doi.casefold())
    if value.lower().startswith(("http://", "https://")):
        parts = urlsplit(value)
        userinfo, separator, host = parts.netloc.rpartition("@")
        authority = (userinfo + separator if separator else "") + host.casefold()
        if host.casefold() in {"doi.org", "dx.doi.org"} and not separator:
            doi = unquote(parts.path.lstrip("/"))
            if DOI_LITERAL.fullmatch(doi):
                return ("doi", doi.casefold())
        return ("url", parts.scheme.lower(), authority, parts.path, parts.query, parts.fragment)
    return ("locator", value)


def file_version(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def validate_schema(state):
    """Reject malformed data before evaluating recorded readiness."""
    def field(obj, key, kind, path, nullable=False, choices=None):
        where = f"{path}.{key}"
        if not isinstance(obj, dict) or key not in obj:
            raise SchemaError(f"缺少字段 {where}")
        value = obj[key]
        if nullable and value is None:
            return value
        if kind == "number":
            ok = finite_number(value)
        else:
            ok = type(value) is kind
        if not ok:
            raise SchemaError(f"字段类型无效 {where}")
        if choices is not None and value not in choices:
            raise SchemaError(f"字段取值无效 {where}: {value!r}")
        return value

    def strings(values, path):
        if any(type(v) is not str or not v.strip() for v in values):
            raise SchemaError(f"{path} 必须是非空字符串数组")

    def text_fields(obj, keys, path, nullable=False):
        for key in keys:
            value = field(obj, key, str, path, nullable)
            if value is not None and not value.strip():
                raise SchemaError(f"空字符串 {path}.{key}；未知值使用 null")

    if isinstance(state, dict) and state.get("schema_version") == 1:
        raise SchemaError("版本 1 台账需按 references/project-state.md 迁移至版本 2；脚本不会覆盖原件")
    field(state, "schema_version", int, "state", choices={2})
    for key in ("brief", "journal", "requirements", "manuscript", "checks"):
        field(state, key, dict, "state")
    text_fields(state["brief"], (
        "object", "scenario", "problem", "method", "language"
    ), "brief", True)
    field(state["brief"], "innovation_focus", str, "brief", True,
          choices=INNOVATION_DIMENSIONS)
    if "narrative_mode" in state["brief"]:
        field(state["brief"], "narrative_mode", str, "brief", True,
              choices=NARRATIVE_MODES)
    journal = state["journal"]
    text_fields(journal, ("name", "official_url", "checked_at"), "journal", True)
    field(journal, "verified", bool, "journal")
    requirements = state["requirements"]
    for key in ("min_references", "min_proved_properties"):
        if field(requirements, key, int, "requirements") < 0:
            raise SchemaError(f"requirements.{key} 不能为负数")
    bounds = field(requirements, "self_citations", list, "requirements")
    if (len(bounds) != 2 or any(type(v) is not int or v < 0 for v in bounds)
            or bounds[0] > bounds[1]):
        raise SchemaError("requirements.self_citations 必须是非负递增整数区间")
    for i, override in enumerate(field(state, "requirement_overrides", list, "state")):
        path = f"requirement_overrides[{i}]"
        key = field(override, "field", str, path, choices=set(DEFAULT_REQUIREMENTS))
        text_fields(override, ("reason", "authorization"), path)
        kind = list if key == "self_citations" else int
        for name in ("from", "to"):
            value = field(override, name, kind, path)
            if kind is int and value < 0:
                raise SchemaError(f"{path}.{name} 不能为负数")
            if kind is list and (len(value) != 2 or any(type(v) is not int or v < 0 for v in value)
                                 or value[0] > value[1]):
                raise SchemaError(f"{path}.{name} 必须是非负递增整数区间")
    for i, author in enumerate(field(state, "required_authors", list, "state")):
        path = f"required_authors[{i}]"
        text_fields(author, ("id", "name", "identity"), path)
        field(author, "identity_verified", bool, path)
        if field(author, "min_citations", int, path) < 1:
            raise SchemaError(f"{path}.min_citations 必须至少为 1")
    manuscript = state["manuscript"]
    text_fields(manuscript, ("body_file", "body_sha256"), "manuscript", True)
    for key in ("abstract_sentences", "conclusion_paragraphs"):
        strings(field(manuscript, key, list, "manuscript"), f"manuscript.{key}")
    field(manuscript, "format_verified", bool, "manuscript")
    field(manuscript, "reference_pages", "number", "manuscript", True)
    chapters = field(manuscript, "chapters", list, "manuscript")
    numbers = []
    for i, chapter in enumerate(chapters):
        path = f"chapters[{i}]"
        numbers.append(field(chapter, "number", int, path))
        field(chapter, "status", str, path, choices={"planned", "draft", "ready"})
        strings(field(chapter, "artifacts", list, path), f"{path}.artifacts")
        field(chapter, "pages", "number", path, True)
    if sorted(numbers) != [1, 2, 3, 4, 5, 6]:
        raise SchemaError("chapters 必须恰好包含不重复的第 1–6 章")
    for key in CHECKS:
        field(state["checks"], key, bool, "checks", True)
    for collection in ("sources", "evidence", "claims", "results", "open_issues"):
        rows = field(state, collection, list, "state")
        for i, row in enumerate(rows):
            path = f"{collection}[{i}]"
            text_fields(row, ("id",), path)
            if collection == "sources":
                text_fields(row, ("locator",), path)
                field(row, "year", int, path, True)
                field(row, "verification", str, path,
                      choices={"unverified", "metadata", "content"})
                for key in ("relevant", "cited"):
                    field(row, key, bool, path)
                field(row, "is_self", bool, path, True)
                for key in ("author_ids", "citation_tokens"):
                    strings(field(row, key, list, path), f"{path}.{key}")
                text_fields(row, ("snapshot_file", "snapshot_sha256"), path, True)
            elif collection == "evidence":
                field(row, "kind", str, path, choices={
                    "literature", "proof", "experiment", "derivation", "implementation"
                })
                field(row, "status", str, path, choices={"pending", "verified", "invalid"})
                text_fields(row, ("locator", "scope", "source_id", "sha256"), path, True)
                strings(field(row, "properties", list, path), f"{path}.properties")
            elif collection == "claims":
                text_fields(row, ("text",), path)
                field(row, "kind", str, path, choices={
                    "novelty", "literature", "theory", "quantitative", "modeling", "application"
                })
                for key in ("evidence_ids", "locations"):
                    strings(field(row, key, list, path), f"{path}.{key}")
                field(row, "innovation_dimension", str, path, True,
                      choices=INNOVATION_DIMENSIONS)
            elif collection == "results":
                text_fields(row, (
                    "claim_id", "evidence_id", "metric", "unit", "scenario"
                ), path)
                field(row, "direction", str, path, choices={"lower", "higher"})
                field(row, "basis", str, path,
                      choices={"relative_percent", "absolute", "percentage_points"})
                for key in ("baseline", "proposed", "reported_value"):
                    field(row, key, "number", path, True)
                text_fields(row, ("reported_text",), path, True)
                if row["reported_text"] is not None:
                    number_text(row["reported_text"])
                for j, mention in enumerate(field(row, "mentions", list, path)):
                    where = f"{path}.mentions[{j}]"
                    field(mention, "location", str, where, choices={"abstract", "body", "conclusion"})
                    text_fields(mention, ("quote", "value_text"), where)
                    number_text(mention["value_text"])
            else:
                text_fields(row, ("detail",), path)
                field(row, "severity", str, path, choices={"blocking", "major", "minor"})
    strings(field(state, "decisions", list, "state"), "decisions")


def audit(state, final=False, project_dir=None):
    """Audit links, file versions, text excerpts and arithmetic; not evidence semantics."""
    validate_schema(state)
    report = {"errors": [], "warnings": [], "calculations": [], "summary": {}}
    project_dir = Path(project_dir) if project_dir is not None else Path.cwd()
    file_cache = {}

    def issue(code, message, hard=False):
        bucket = "errors" if hard or final else "warnings"
        report[bucket].append({"code": code, "message": message})

    def checked_file(locator, digest, label, hard=False, read_content=False):
        if locator is None or digest is None:
            issue("missing_artifact", f"{label} 缺本地文件或 SHA-256", hard)
            return None
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            issue("invalid_digest", f"{label} 的 SHA-256 格式无效", True)
            return None
        if "://" in locator or locator.startswith("urn:"):
            issue("nonlocal_artifact", f"{label} 需要本地资料快照，不能仅用网址代替", True)
            return None
        path = Path(locator.split("#", 1)[0])
        if not path.is_absolute():
            path = project_dir / path
        try:
            path = path.resolve(strict=True)
            version = file_version(path.stat())
            snapshot = file_cache.get(path)
            if (snapshot is None or snapshot["version"] != version
                    or (read_content and snapshot["content"] is None)):
                checksum = hashlib.sha256()
                chunks = [] if read_content else None
                size = 0
                with path.open("rb") as stream:
                    opened_version = file_version(os.fstat(stream.fileno()))
                    for chunk in iter(lambda: stream.read(HASH_CHUNK_SIZE), b""):
                        checksum.update(chunk)
                        size += len(chunk)
                        if chunks is not None:
                            chunks.append(chunk)
                    closed_version = file_version(os.fstat(stream.fileno()))
                if not version == opened_version == closed_version == file_version(path.stat()):
                    issue("artifact_changed_during_read", f"{label} 在读取过程中已变化，需要重新核验: {path}", True)
                    return None
                snapshot = {
                    "version": version, "digest": checksum.hexdigest(), "size": size,
                    "content": b"".join(chunks) if chunks is not None else None,
                }
                file_cache[path] = snapshot
        except (OSError, RuntimeError) as exc:
            issue("missing_artifact", f"{label} 文件无法读取: {path} ({exc})", hard)
            return None
        if not snapshot["size"]:
            issue("empty_artifact", f"{label} 文件为空: {path}", True)
            return None
        if snapshot["digest"] != digest.lower():
            issue("stale_artifact", f"{label} 文件已变化，需要重新核验: {path}", True)
            return None
        return snapshot["content"] if read_content else True

    manuscript = state["manuscript"]
    body_bytes = checked_file(manuscript["body_file"], manuscript["body_sha256"], "审查正文", read_content=True)
    body_text = None
    if body_bytes is not None:
        try:
            body_text = body_bytes.decode("utf-8-sig")
        except UnicodeError:
            issue("unsupported_body_format", "审查正文需为 UTF-8 Markdown、LaTeX 或纯文本导出", True)
    normalized_body = " ".join(body_text.split()) if body_text is not None else None
    for key in ("abstract_sentences", "conclusion_paragraphs"):
        for text in manuscript[key]:
            if normalized_body is not None and " ".join(text.split()) not in normalized_body:
                issue("manuscript_text_mismatch", f"台账中的 {key} 片段未在实际正文找到", True)

    overrides = {}
    for item in state["requirement_overrides"]:
        key = item["field"]
        if key in overrides:
            issue("duplicate_override", f"同一标准有重复的有效调整记录: {key}", True)
        overrides[key] = item
        if item["from"] != DEFAULT_REQUIREMENTS[key] or item["to"] != state["requirements"][key]:
            issue("invalid_override", f"标准调整记录与默认值或现值不匹配: {key}", True)
    for key, default in DEFAULT_REQUIREMENTS.items():
        if state["requirements"][key] != default and key not in overrides:
            issue("unauthorized_requirement_change", f"标准 {key} 已变化但缺具体授权记录", True)

    indexes = {}
    seen = set()
    for collection in ("required_authors", "sources", "evidence", "claims", "results", "open_issues"):
        indexes[collection] = {}
        for row in state[collection]:
            if row["id"] in seen:
                issue("duplicate_id", f"重复 ID: {row['id']}", True)
            seen.add(row["id"])
            indexes[collection][row["id"]] = row
    sources, evidence, claims = (indexes[k] for k in ("sources", "evidence", "claims"))
    required_authors = indexes["required_authors"]
    locators = set()
    cited_sources = []
    for source in state["sources"]:
        key = source_locator_key(source["locator"])
        if key in locators:
            issue("duplicate_source", f"重复来源位置: {source['id']}", True)
            continue
        locators.add(key)
        if source["cited"]:
            if source["verification"] == "content":
                checked_file(source["snapshot_file"], source["snapshot_sha256"], f"文献 {source['id']}", True)
            if not source["citation_tokens"]:
                issue("missing_citation_token", f"文献缺正文引文标记: {source['id']}")
            tokens_present = normalized_body is not None and any(
                " ".join(token.split()) in normalized_body for token in source["citation_tokens"]
            )
            if normalized_body is not None and not tokens_present:
                issue("citation_absent_from_body", f"文献未在实际审查正文引用: {source['id']}", True)
            if set(source["author_ids"]) - set(required_authors):
                issue("unknown_required_author", f"文献包含未登记的必引作者 ID: {source['id']}", True)
            if not source["relevant"]:
                issue("irrelevant_citation", f"已引用不相关来源: {source['id']}", True)
            if source["verification"] != "content":
                issue("unread_citation", f"引用内容尚未核对: {source['id']}")
            if source["is_self"] is None:
                issue("unknown_authorship", f"自引身份未确认: {source['id']}")
            if source["relevant"] and tokens_present:
                cited_sources.append(source)
    author_counts = {}
    for author in state["required_authors"]:
        count = sum(author["id"] in source["author_ids"] for source in cited_sources)
        author_counts[author["id"]] = count
        if not author["identity_verified"]:
            issue("required_author_identity_pending", f"必引作者身份未核对: {author['name']}")
        if count < author["min_citations"]:
            issue("required_author_missing", f"必引作者 {author['name']} 已引用 {count} 篇，要求至少 {author['min_citations']} 篇")
    proof_properties = set()
    for entry in state["evidence"]:
        if entry["kind"] == "literature":
            source = sources.get(entry["source_id"])
            if source is None:
                issue("broken_source_link", f"文献证据缺少有效来源: {entry['id']}", True)
            elif entry["status"] == "verified" and (
                    source["verification"] != "content" or not source["relevant"]):
                issue("invalid_verification", f"证据来源未核对或不相关: {entry['id']}", True)
        elif entry["source_id"] is not None:
            issue("unexpected_source_link", f"非文献证据的 source_id 应为 null: {entry['id']}", True)
        if entry["status"] == "verified":
            checked_file(entry["locator"], entry["sha256"], f"证据 {entry['id']}", True)
            if not entry["locator"] or not entry["scope"]:
                issue("empty_verified_evidence", f"已核验证据缺定位或适用范围: {entry['id']}", True)
            elif entry["kind"] == "proof":
                proof_properties.update(PROPERTIES.intersection(entry["properties"]))
        if entry["properties"] and entry["kind"] != "proof":
            issue("nonproof_properties", f"只有 proof 记录可列已证性质: {entry['id']}", True)
    result_claims = {row["claim_id"] for row in state["results"]}
    narrative = state["brief"].get("narrative_mode")
    if narrative is None:
        issue("narrative_mode_pending", "需先询问使用者选择场景论或方法论，并登记实际选择")
    focus = state["brief"]["innovation_focus"]
    if focus is None:
        issue("innovation_focus_pending", "需从对象、场景、方法中选定一个创新主线")
    novelty_claims = [claim for claim in state["claims"] if claim["kind"] == "novelty"]
    if not novelty_claims:
        issue("missing_innovation_claim", "尚未记录所选创新主线的具体创新主张")
    for claim in state["claims"]:
        if not claim["locations"]:
            issue("missing_claim_location", f"主张缺稿内位置: {claim['id']}")
        links = [evidence.get(key) for key in claim["evidence_ids"]]
        if any(row is None for row in links):
            issue("broken_evidence_link", f"主张指向不存在的证据: {claim['id']}", True)
        if not links or any(row is not None and row["status"] != "verified" for row in links):
            issue("unsupported_claim", f"主张证据未完成: {claim['id']}")
        needed = {"theory": "proof", "quantitative": "experiment", "literature": "literature"}.get(claim["kind"])
        if needed and not any(row and row["kind"] == needed and row["status"] == "verified" for row in links):
            issue("missing_evidence_kind", f"{claim['id']} 缺已核验 {needed} 证据")
        if claim["kind"] == "novelty" and not any(
                row and row["kind"] == "literature" and row["status"] == "verified" for row in links):
            issue("unverified_novelty", f"创新主张缺已核验相关工作比较: {claim['id']}")
        if claim["kind"] == "novelty" and (claim["innovation_dimension"] is None
                                           or claim["innovation_dimension"] != focus):
            issue("innovation_focus_mismatch", f"创新主张与选定创新主线不一致: {claim['id']}")
        if claim["kind"] == "quantitative" and claim["id"] not in result_claims:
            issue("missing_result", f"定量主张缺复算记录: {claim['id']}")
    abstract_comparison_found = False
    for row in state["results"]:
        claim = claims.get(row["claim_id"])
        entry = evidence.get(row["evidence_id"])
        if claim is None or claim["kind"] != "quantitative":
            issue("broken_result_claim", f"结果缺有效定量主张: {row['id']}", True)
        elif row["evidence_id"] not in claim["evidence_ids"]:
            issue("result_claim_mismatch", f"结果与主张证据不一致: {row['id']}", True)
        if entry is None or entry["kind"] != "experiment":
            issue("broken_result_evidence", f"结果缺实验记录: {row['id']}", True)
        elif entry["status"] != "verified":
            issue("unverified_result", f"实验记录尚未核验: {row['id']}")
        baseline, proposed, reported = (row[k] for k in ("baseline", "proposed", "reported_value"))
        if baseline is None or proposed is None or reported is None or row["reported_text"] is None:
            issue("incomplete_result", f"比较数值待补: {row['id']}")
            continue
        delta = baseline - proposed if row["direction"] == "lower" else proposed - baseline
        if row["basis"] == "relative_percent":
            if baseline <= 0 or proposed < 0:
                issue("undefined_relative_comparison", f"相对比较要求正基线和非负指标: {row['id']}", True)
                continue
            expected = delta / baseline * 100
        else:
            if row["basis"] == "percentage_points" and not (0 <= baseline <= 100 and 0 <= proposed <= 100):
                issue("invalid_percentage", f"百分点比较必须使用 0–100 的百分比数值: {row['id']}", True)
                continue
            expected = delta
        if not math.isfinite(expected):
            issue("numeric_overflow", f"比较计算超出有限数值范围: {row['id']}", True)
            continue
        report["calculations"].append({"id": row["id"], "expected": expected, "reported": reported, "basis": row["basis"]})
        literal_value, _ = number_text(row["reported_text"])
        if not math.isclose(literal_value, reported, rel_tol=1e-12, abs_tol=0.0):
            issue("reported_text_mismatch", f"{row['id']} 的报告数字与数字文本不一致", True)
        if not matches_report(expected, row["reported_text"]):
            issue("wrong_improvement", f"{row['id']} 改进值应为 {expected:.10g}，稿中为 {reported:.10g}", True)
        if not row["mentions"]:
            issue("missing_result_mention", f"比较结果缺实际正文数字片段: {row['id']}")
        for mention in row["mentions"]:
            quote = " ".join(mention["quote"].split())
            if normalized_body is None:
                issue("result_body_unchecked", f"无法核对结果的实际正文片段: {row['id']}")
                continue
            if quote not in normalized_body:
                issue("result_quote_missing", f"结果片段未在实际正文找到: {row['id']}", True)
                continue
            if not number_in_quote(mention["quote"], mention["value_text"]):
                issue("result_value_not_in_quote", f"声明的数字未在结果片段找到: {row['id']}", True)
                continue
            if not matches_report(expected, mention["value_text"]):
                issue("manuscript_result_mismatch", f"实际正文中的改进值与复算结果不一致: {row['id']}", True)
                continue
            if mention["location"] == "abstract":
                if len(manuscript["abstract_sentences"]) == 5 and quote == " ".join(manuscript["abstract_sentences"][4].split()):
                    abstract_comparison_found = True
                else:
                    issue("abstract_result_location_mismatch", f"摘要结果片段需对应摘要第五句: {row['id']}", True)
            elif mention["location"] == "conclusion" and quote not in [" ".join(p.split()) for p in manuscript["conclusion_paragraphs"]]:
                issue("conclusion_result_location_mismatch", f"总结结果片段需对应实际总结段: {row['id']}", True)
    if not abstract_comparison_found:
        issue("abstract_comparison_missing", "摘要第五句缺已复算并在实际正文定位的比较结果")
    req, manuscript = state["requirements"], state["manuscript"]
    count = len(cited_sources)
    self_count = sum(row["is_self"] is True for row in cited_sources)
    report["summary"] = {"references": count, "self_citations": self_count,
                         "proved_properties_recorded": sorted(proof_properties),
                         "required_author_citations": author_counts,
                         "innovation_focus": focus,
                         "narrative_mode": narrative,
                         "mode": "final" if final else "draft"}
    if count < req["min_references"]:
        issue("reference_target", f"相关且已引用文献 {count} 篇，目标至少 {req['min_references']} 篇")
    low, high = req["self_citations"]
    if not low <= self_count <= high:
        issue("self_citation_target", f"相关自引 {self_count} 篇，目标 {low}–{high} 篇")
    if len(proof_properties) < req["min_proved_properties"]:
        issue("proof_target", f"台账已证性质 {len(proof_properties)} 项，目标至少 {req['min_proved_properties']} 项")
    for key in ("object", "scenario", "problem", "method", "language"):
        if state["brief"][key] is None:
            issue("incomplete_brief", f"研究信息待补: {key}")
    journal = state["journal"]
    if journal["verified"] and any(journal[k] is None for k in ("name", "official_url", "checked_at")):
        issue("empty_journal_verification", "期刊核验声明缺官方来源或日期", True)
    if not journal["verified"] or not manuscript["format_verified"]:
        issue("format_pending", "官方模板或实际排版尚未核验")
    for key, wanted in (("abstract_sentences", 5), ("conclusion_paragraphs", 2)):
        if len(manuscript[key]) != wanted:
            issue("text_structure", f"{key} 当前 {len(manuscript[key])} 项，要求 {wanted} 项；另需人工确认句/段边界")
    for chapter in manuscript["chapters"]:
        number, pages = chapter["number"], chapter["pages"]
        if chapter["status"] != "ready" or not chapter["artifacts"]:
            issue("chapter_pending", f"第 {number} 章未完成或缺文件位置")
        for artifact in chapter["artifacts"]:
            if "://" in artifact or artifact.startswith("urn:"):
                issue("nonlocal_artifact", f"第 {number} 章需要本地文件定位", True)
                continue
            path = Path(artifact.split("#", 1)[0])
            if not path.is_absolute():
                path = project_dir / path
            try:
                exists = path.is_file() and path.stat().st_size > 0
            except OSError:
                exists = False
            if not exists:
                issue("missing_artifact", f"第 {number} 章文件不存在、为空或无法读取: {path}",
                      chapter["status"] == "ready")
        if pages is not None and pages <= 0:
            issue("invalid_pages", f"第 {number} 章页数必须大于零", True)
        if number in (1, 2, 3, 4, 5):
            if pages is None:
                issue("pages_pending", f"第 {number} 章实际页数待核验")
            elif number in (2, 3, 4) and pages > 3:
                issue("chapter_page_limit", f"第 {number} 章 {pages:g} 页，超过一般 3 页上限")
            elif number in (2, 3, 4) and not 1.5 <= pages <= 2:
                report["warnings"].append({"code": "page_target", "message": f"第 {number} 章偏离 1.5–2 页目标：{pages:g}"})
            elif number in (1, 5) and abs(pages - (1.5 if number == 1 else 3)) > 0.25:
                report["warnings"].append({"code": "page_target", "message": f"第 {number} 章篇幅偏离默认目标：{pages:g} 页"})
    ref_pages = manuscript["reference_pages"]
    if ref_pages is None:
        issue("reference_pages_pending", "参考文献实际页数待核验")
    elif not 1 <= ref_pages <= 1.5:
        if ref_pages <= 0:
            issue("invalid_reference_pages", "参考文献实际页数必须大于零", True)
        else:
            report["warnings"].append({"code": "reference_page_target", "message": f"参考文献 {ref_pages:g} 页，目标 1–1.5 页"})
    for key in CHECKS:
        if state["checks"][key] is not True:
            issue("manual_check_pending", f"人工核对尚未通过: {key}")
    if not state["claims"]:
        issue("missing_claims", "尚未记录贡献与论证主张")
    if not state["results"]:
        issue("missing_comparison", "尚未记录第 5.3 节与摘要所需的定量比较")
    for item in state["open_issues"]:
        if item["severity"] in ("blocking", "major"):
            issue("open_issue", f"未解决问题 {item['id']}: {item['detail']}")
        else:
            report["warnings"].append({"code": "minor_issue", "message": item["detail"]})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="只读核查泛控制类论文台账、文件版本与正文片段；证据语义和数学正确性仍需人工核验")
    parser.add_argument("state", type=Path)
    parser.add_argument("--final", action="store_true", help="检查整篇完成条件")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args(argv)
    try:
        state = json.loads(args.state.read_text(encoding="utf-8-sig"))
        report = audit(state, args.final, project_dir=args.state.resolve().parent)
    except (OSError, UnicodeError, ValueError, OverflowError, RecursionError) as exc:
        if args.json:
            print(json.dumps({"errors": [{"code": "invalid_input", "message": str(exc)}]}, ensure_ascii=False))
        else:
            print(f"台账输入无效：{exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"台账检查：{len(report['errors'])} 个错误，{len(report['warnings'])} 个警告")
        print("范围：台账、作者覆盖、文件版本、正文片段与算术；数学正确性和论证相关性仍需人工核对。")
        for category, label in (("errors", "错误"), ("warnings", "警告")):
            for item in report[category]:
                print(f"[{label}/{item['code']}] {item['message']}")
        for row in report["calculations"]:
            print(f"[复算] {row['id']}: {row['expected']:.10g} ({row['basis']})")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
