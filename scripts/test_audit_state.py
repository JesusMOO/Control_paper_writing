#!/usr/bin/env python3
"""Synthetic ledger regression cases; fixtures are not research evidence."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from audit_state import CHECKS, SchemaError, audit


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sync_body(state, directory):
    """Write only synthetic fixture text and record its current fingerprint."""
    manuscript = state["manuscript"]
    text = "\n\n".join(manuscript["abstract_sentences"] + manuscript["conclusion_paragraphs"])
    text += "\n\n" + "\n".join(f"合成相关工作 [@S{i}]。" for i in range(40))
    body = Path(directory) / "body.md"
    body.write_text(text, encoding="utf-8")
    manuscript.update(body_file=str(body), body_sha256=digest(body))


def fixture(directory):
    directory = Path(directory)
    state = json.loads((ROOT / "assets/paper-state.json").read_text(encoding="utf-8"))
    state["brief"].update(object="测试对象", scenario="测试场景", problem="测试问题",
                          method="测试方法", language="中文", innovation_focus="method",
                          narrative_mode="scenario")
    state["journal"].update(name="非真实期刊的测试夹具", official_url="urn:fixture:journal",
                            checked_at="2026-10-11", verified=True)
    state["manuscript"]["abstract_sentences"] = [f"测试句 {i}。" for i in range(5)]
    state["manuscript"]["abstract_sentences"][4] = "合成比较中的误差降低20%。"
    state["manuscript"]["conclusion_paragraphs"] = ["测试总结。", "测试展望。"]
    state["manuscript"].update(format_verified=True, reference_pages=1.2)
    for chapter in state["manuscript"]["chapters"]:
        chapter.update(status="ready", artifacts=[str(directory / "body.md")],
                       pages=1.5 if chapter["number"] == 1 else 3 if chapter["number"] == 5 else 2)
    state["checks"] = dict.fromkeys(CHECKS, True)
    state["required_authors"] = [dict(id="A1", name="合成作者", identity="测试身份",
                                      identity_verified=True, min_citations=1)]
    snapshot = directory / "sources.txt"
    snapshot.write_text("合成文献内容，仅作为自动测试夹具。", encoding="utf-8")
    proof = directory / "proof.md"
    proof.write_text("合成证明内容，仅作为自动测试夹具。", encoding="utf-8")
    experiment = directory / "experiment.csv"
    experiment.write_text("baseline,proposed\n10,8\n", encoding="utf-8")
    state["sources"] = [dict(id=f"S{i}", locator=f"urn:fixture:source:{i}", year=2026,
                             verification="content", relevant=True, cited=True, is_self=i < 6,
                             author_ids=["A1"] if i == 0 else [], citation_tokens=[f"[@S{i}]"],
                             snapshot_file=str(snapshot), snapshot_sha256=digest(snapshot))
                        for i in range(40)]
    state["evidence"] = [
        dict(id="E1", kind="literature", status="verified", locator=str(snapshot), sha256=digest(snapshot),
             scope="仅用于测试", source_id="S0", properties=[]),
        dict(id="E2", kind="proof", status="verified", locator=str(proof), sha256=digest(proof),
             scope="仅用于测试", source_id=None, properties=["stability"]),
        dict(id="E3", kind="experiment", status="verified", locator=str(experiment), sha256=digest(experiment),
             scope="仅用于测试", source_id=None, properties=[]),
    ]
    state["claims"] = [
        dict(id="C1", text="测试性质", kind="theory", evidence_ids=["E2"], locations=["3.3"], innovation_dimension=None),
        dict(id="C2", text="测试量化主张", kind="quantitative", evidence_ids=["E3"], locations=["5.3"], innovation_dimension=None),
        dict(id="C3", text="测试创新主张", kind="novelty", evidence_ids=["E1"], locations=["1"], innovation_dimension="method"),
    ]
    state["results"] = [dict(id="R1", claim_id="C2", evidence_id="E3", metric="测试误差",
                             unit="m", scenario="仅用于测试", direction="lower",
                             basis="relative_percent", baseline=10.0, proposed=8.0,
                             reported_value=20.0, reported_text="20",
                             mentions=[dict(location="abstract", quote=state["manuscript"]["abstract_sentences"][4], value_text="20")])]
    sync_body(state, directory)
    return state


def codes(report, category="errors"):
    return {item["code"] for item in report[category]}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name)
        self.state = fixture(self.workspace)

    def change_comparison(self, **changes):
        row = self.state["results"][0]
        row.update(changes)
        self.state["manuscript"]["abstract_sentences"][4] = f"合成比较中的改善为{row['reported_text']}。"
        row["mentions"] = [dict(location="abstract", quote=self.state["manuscript"]["abstract_sentences"][4],
                                value_text=row["reported_text"])]
        sync_body(self.state, self.workspace)

    def test_complete_record_and_no_mutation(self):
        before = copy.deepcopy(self.state)
        report = audit(self.state, final=True)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["calculations"][0]["expected"], 20.0)
        self.assertEqual(self.state, before)

    def test_reference_target_requires_forty_distinct_cited_sources(self):
        self.assertEqual(self.state["requirements"]["min_references"], 40)
        report = audit(self.state, final=True)
        self.assertEqual(report["summary"]["references"], 40)
        self.assertEqual(report["errors"], [])
        self.state["sources"][-1]["cited"] = False
        report = audit(self.state, final=True)
        self.assertEqual(report["summary"]["references"], 39)
        self.assertIn("reference_target", codes(report))

    def test_missing_narrative_choice_is_pending_in_draft_and_blocks_final(self):
        for omitted in (False, True):
            with self.subTest(omitted=omitted):
                state = copy.deepcopy(self.state)
                if omitted:
                    state["brief"].pop("narrative_mode")
                else:
                    state["brief"]["narrative_mode"] = None
                before = copy.deepcopy(state)
                draft = audit(state)
                self.assertEqual(draft["errors"], [])
                self.assertIn("narrative_mode_pending", codes(draft, "warnings"))
                self.assertIn("narrative_mode_pending", codes(audit(state, final=True)))
                self.assertEqual(state, before)

    def test_narrative_choice_is_independent_of_innovation_dimension(self):
        for narrative in ("scenario", "method"):
            for dimension in ("object", "scenario", "method"):
                with self.subTest(narrative=narrative, dimension=dimension):
                    self.state["brief"].update(narrative_mode=narrative, innovation_focus=dimension)
                    self.state["claims"][2]["innovation_dimension"] = dimension
                    report = audit(self.state, final=True)
                    self.assertEqual(report["errors"], [])
                    self.assertEqual(report["summary"]["narrative_mode"], narrative)

    def test_unknown_narrative_mode_is_rejected(self):
        self.state["brief"]["narrative_mode"] = "auto"
        with self.assertRaises(SchemaError):
            audit(self.state)

    def test_empty_template_is_draft_but_not_final(self):
        state = json.loads((ROOT / "assets/paper-state.json").read_text(encoding="utf-8"))
        self.assertFalse(audit(state)["errors"])
        self.assertIn("missing_comparison", codes(audit(state), "warnings"))
        self.assertIn("reference_target", codes(audit(state, final=True)))

    def test_ready_chapter_requires_existing_local_file(self):
        self.state["manuscript"]["chapters"][1]["artifacts"] = [str(self.workspace / "missing.md") + "#第二章"]
        self.assertIn("missing_artifact", codes(audit(self.state, final=True)))

    def test_result_literal_cannot_match_scientific_exponent(self):
        sentence = "合成比较中的误差降低2e20%。"
        self.state["manuscript"]["abstract_sentences"][4] = sentence
        self.state["results"][0]["mentions"][0]["quote"] = sentence
        sync_body(self.state, self.workspace)
        self.assertIn("result_value_not_in_quote", codes(audit(self.state, final=True)))

    def test_pending_proof_cannot_count_as_proved(self):
        self.state["evidence"][1]["status"] = "pending"
        report = audit(self.state, final=True)
        self.assertIn("proof_target", codes(report))
        self.assertIn("missing_evidence_kind", codes(report))

    def test_broken_and_duplicate_ids(self):
        self.state["claims"][0]["evidence_ids"] = ["ABSENT"]
        self.state["claims"][1]["id"] = "E1"
        report = audit(self.state)
        self.assertIn("broken_evidence_link", codes(report))
        self.assertIn("duplicate_id", codes(report))

    def test_duplicate_and_irrelevant_sources_cannot_fill_quota(self):
        self.state["sources"][1]["locator"] = self.state["sources"][0]["locator"]
        self.state["sources"][2]["relevant"] = False
        report = audit(self.state, final=True)
        self.assertEqual(report["summary"]["references"], 38)
        self.assertIn("duplicate_source", codes(report))
        self.assertIn("irrelevant_citation", codes(report))
        self.assertIn("reference_target", codes(report))

    def test_metadata_is_not_content_verification(self):
        self.state["sources"][0]["verification"] = "metadata"
        report = audit(self.state, final=True)
        self.assertIn("unread_citation", codes(report))
        self.assertIn("invalid_verification", codes(report))

    def test_wrong_relative_improvement_rejected_even_in_draft(self):
        self.change_comparison(reported_value=25, reported_text="25")
        self.assertIn("wrong_improvement", codes(audit(self.state)))

    def test_zero_baseline_cannot_produce_relative_gain(self):
        self.state["results"][0]["baseline"] = 0
        self.assertIn("undefined_relative_comparison", codes(audit(self.state)))

    def test_percentage_points_and_relative_percent_are_distinct(self):
        self.change_comparison(baseline=80, proposed=90, direction="higher", unit="%",
                               basis="percentage_points", reported_value=10, reported_text="10")
        self.assertFalse(audit(self.state)["errors"])
        self.change_comparison(basis="relative_percent", reported_value=12.5, reported_text="12.5")
        self.assertFalse(audit(self.state)["errors"])
        self.change_comparison(reported_value=10, reported_text="10")
        self.assertIn("wrong_improvement", codes(audit(self.state)))

    def test_negative_improvement_is_preserved(self):
        self.change_comparison(proposed=12, reported_value=-20, reported_text="-20")
        self.assertFalse(audit(self.state)["errors"])
        self.assertEqual(audit(self.state)["calculations"][0]["expected"], -20)

    def test_boolean_nan_missing_and_bad_enum_are_schema_errors(self):
        for value in (True, float("nan"), "10"):
            state = copy.deepcopy(self.state)
            state["results"][0]["baseline"] = value
            with self.assertRaises(SchemaError):
                audit(state)
        for operation in (lambda s: s.pop("brief"),
                          lambda s: s["evidence"][0].update(status="complete")):
            state = copy.deepcopy(self.state)
            operation(state)
            with self.assertRaises(SchemaError):
                audit(state)

    def test_duplicate_chapter_is_schema_error(self):
        self.state["manuscript"]["chapters"][1]["number"] = 1
        with self.assertRaises(SchemaError):
            audit(self.state)

    def test_empty_verified_evidence_rejected(self):
        self.state["evidence"][1]["locator"] = None
        self.assertIn("empty_verified_evidence", codes(audit(self.state)))

    def test_result_and_claim_must_reference_same_experiment(self):
        self.state["claims"][1]["evidence_ids"] = ["E2"]
        self.assertIn("result_claim_mismatch", codes(audit(self.state)))

    def test_unknown_self_citations_and_manual_checks_block_final(self):
        self.state["sources"][0]["is_self"] = None
        self.state["checks"]["flowchart_and_equations"] = None
        report = audit(self.state, final=True)
        self.assertIn("unknown_authorship", codes(report))
        self.assertIn("self_citation_target", codes(report))
        self.assertIn("manual_check_pending", codes(report))

    def test_cli_exit_codes_and_read_only_behavior(self):
        script = ROOT / "scripts/audit_state.py"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper-state.json"
            original = json.dumps(self.state, ensure_ascii=False)
            path.write_text(original, encoding="utf-8")
            command = [sys.executable, str(script), str(path), "--final", "--json"]
            good = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(good.returncode, 0, good.stderr + good.stdout)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.state["results"][0]["reported_value"] = 99
            path.write_text(json.dumps(self.state), encoding="utf-8")
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            path.write_text("not json", encoding="utf-8")
            bad = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2)
            self.assertIn("invalid_input", codes(json.loads(bad.stdout)))

    def test_required_author_missing_blocks_final_without_manual_issue(self):
        self.state["sources"][0]["author_ids"] = []
        self.assertIn("required_author_missing", codes(audit(self.state, final=True)))

    def test_required_author_count_and_identity_are_checked(self):
        self.state["required_authors"][0].update(min_citations=2, identity_verified=False)
        report = audit(self.state, final=True)
        self.assertIn("required_author_missing", codes(report))
        self.assertIn("required_author_identity_pending", codes(report))

    def test_missing_required_author_field_is_schema_error(self):
        self.state.pop("required_authors")
        with self.assertRaises(SchemaError):
            audit(self.state)

    def test_source_without_actual_body_citation_cannot_cover_author(self):
        self.state["sources"][0]["citation_tokens"] = ["[@MISSING]"]
        report = audit(self.state, final=True)
        self.assertIn("citation_absent_from_body", codes(report))
        self.assertIn("required_author_missing", codes(report))

    def test_standard_cannot_change_without_specific_authorization(self):
        self.state["requirements"].update(min_references=1, min_proved_properties=0)
        self.assertIn("unauthorized_requirement_change", codes(audit(self.state, final=True)))

    def test_documented_matching_override_is_allowed(self):
        self.state["requirements"]["min_references"] = 1
        self.state["requirement_overrides"] = [dict(field="min_references", **{
            "from": 40, "to": 1, "reason": "合成试验明确调整", "authorization": "合成用户请求定位"})]
        self.assertFalse(audit(self.state, final=True)["errors"])
        self.state["requirement_overrides"][0]["to"] = 2
        self.assertIn("invalid_override", codes(audit(self.state, final=True)))

    def test_missing_evidence_file_and_changed_proof_block_final(self):
        Path(self.state["evidence"][1]["locator"]).unlink()
        self.assertIn("missing_artifact", codes(audit(self.state, final=True)))
        proof = Path(self.state["evidence"][1]["locator"])
        proof.write_text("修改后的合成证明", encoding="utf-8")
        self.assertIn("stale_artifact", codes(audit(self.state, final=True)))

    def test_body_change_invalidates_recorded_verification(self):
        Path(self.state["manuscript"]["body_file"]).write_text("修改后的正文", encoding="utf-8")
        self.assertIn("stale_artifact", codes(audit(self.state, final=True)))

    def test_abstract_99_cannot_pass_with_20_in_results(self):
        self.state["manuscript"]["abstract_sentences"][4] = "合成比较中的误差降低99%。"
        sync_body(self.state, self.workspace)
        self.state["results"][0]["mentions"][0].update(
            quote=self.state["manuscript"]["abstract_sentences"][4], value_text="99")
        report = audit(self.state, final=True)
        self.assertIn("manuscript_result_mismatch", codes(report))
        self.assertIn("abstract_comparison_missing", codes(report))

    def test_stale_abstract_text_cannot_pass_against_actual_file(self):
        self.state["manuscript"]["abstract_sentences"][4] = "错误的摘要99%。"
        self.assertIn("manuscript_text_mismatch", codes(audit(self.state, final=True)))

    def test_absolute_small_value_does_not_use_global_005_tolerance(self):
        self.change_comparison(basis="absolute", baseline=0.001, proposed=0.0008,
                               reported_value=0.04, reported_text="0.04")
        self.assertIn("wrong_improvement", codes(audit(self.state, final=True)))
        self.change_comparison(reported_value=0.0002, reported_text="0.0002")
        self.assertFalse(audit(self.state, final=True)["errors"])

    def test_paper_rounding_precision_is_respected(self):
        self.change_comparison(baseline=3, proposed=2, reported_value=33.33, reported_text="33.33")
        self.assertFalse(audit(self.state, final=True)["errors"])
        self.change_comparison(reported_value=33.34, reported_text="33.34")
        self.assertIn("wrong_improvement", codes(audit(self.state, final=True)))

    def test_negative_reference_pages_are_errors(self):
        self.state["manuscript"]["reference_pages"] = -1
        self.assertIn("invalid_reference_pages", codes(audit(self.state, final=True)))

    def test_huge_integer_reports_schema_error_and_cli_exit_2(self):
        self.state["results"][0]["baseline"] = 10**400
        with self.assertRaises(SchemaError):
            audit(self.state)
        path = self.workspace / "state.json"
        path.write_text(json.dumps(self.state), encoding="utf-8")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/audit_state.py"), str(path), "--json"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_object_or_scenario_innovation_does_not_require_method_innovation(self):
        for dimension in ("object", "scenario"):
            self.state["brief"]["innovation_focus"] = dimension
            self.state["claims"][2]["innovation_dimension"] = dimension
            self.assertFalse(audit(self.state, final=True)["errors"])

    def test_innovation_focus_must_match_novelty_claim(self):
        self.state["brief"]["innovation_focus"] = "object"
        self.assertIn("innovation_focus_mismatch", codes(audit(self.state, final=True)))

    def test_v1_ledger_gets_clear_migration_error(self):
        self.state["schema_version"] = 1
        with self.assertRaisesRegex(SchemaError, "迁移"):
            audit(self.state)

    def test_relative_files_resolve_against_state_directory_not_cwd(self):
        self.state["manuscript"]["body_file"] = "body.md"
        for source in self.state["sources"]:
            source["snapshot_file"] = "sources.txt"
        for entry in self.state["evidence"]:
            entry["locator"] = Path(entry["locator"]).name
        self.assertFalse(audit(self.state, final=True, project_dir=self.workspace)["errors"])

    def test_latex_scientific_numbers_match_value_and_precision(self):
        self.change_comparison(basis="absolute", baseline=0.001, proposed=0.0008,
                               reported_value=0.0002, reported_text="0.0002")
        for expression, literal in (
            (r"$2\times 10^{-4}$", "2e-4"),
            (r"$2.00\,\cdot\,10^{-4}$", "0.000200"),
            (r"$2 \times 10^{−4}$", "2E-4"),
            ("2×10^{-4}", "0.0002"),
        ):
            with self.subTest(expression=expression):
                sentence = f"合成比较中的改善为{expression}。"
                self.state["manuscript"]["abstract_sentences"][4] = sentence
                self.state["results"][0]["mentions"] = [
                    dict(location="abstract", quote=sentence, value_text=literal)]
                sync_body(self.state, self.workspace)
                self.assertEqual(audit(self.state, final=True)["errors"], [])

    def test_latex_exponent_cannot_be_used_as_comparison_value(self):
        sentence = r"合成比较中的误差降低 $2\times10^{20}$%。"
        self.state["manuscript"]["abstract_sentences"][4] = sentence
        self.state["results"][0]["mentions"][0]["quote"] = sentence
        sync_body(self.state, self.workspace)
        self.assertIn("result_value_not_in_quote", codes(audit(self.state, final=True)))

    def test_latex_comparison_cannot_hide_wrong_exponent_or_precision(self):
        self.change_comparison(basis="absolute", baseline=0.001, proposed=0.0008,
                               reported_value=0.0002, reported_text="0.0002")
        for expression, literal in (
            (r"$2\times10^{-3}$", "2e-4"),
            (r"$2.00\times10^{-4}$", "2e-4"),
        ):
            with self.subTest(expression=expression):
                sentence = f"合成比较中的改善为{expression}。"
                self.state["manuscript"]["abstract_sentences"][4] = sentence
                self.state["results"][0]["mentions"] = [
                    dict(location="abstract", quote=sentence, value_text=literal)]
                sync_body(self.state, self.workspace)
                self.assertIn("result_value_not_in_quote", codes(audit(self.state, final=True)))

    def test_case_sensitive_source_paths_and_queries_are_distinct(self):
        for first, second in (
            ("https://example.test/PaperA", "https://example.test/papera"),
            ("https://example.test/paper?id=A", "https://example.test/paper?id=a"),
            ("/papers/PaperA.pdf", "/papers/papera.pdf"),
        ):
            with self.subTest(first=first, second=second):
                self.state["sources"][0]["locator"] = first
                self.state["sources"][1]["locator"] = second
                self.assertEqual(audit(self.state, final=True)["errors"], [])

    def test_http_scheme_and_host_case_do_not_hide_duplicate_sources(self):
        self.state["sources"][0]["locator"] = "HTTPS://EXAMPLE.TEST/PaperA"
        self.state["sources"][1]["locator"] = "https://example.test/PaperA"
        self.assertIn("duplicate_source", codes(audit(self.state, final=True)))

    def test_doi_forms_are_deduplicated_without_folding_other_url_paths(self):
        for first, second in (
            ("10.1234/AbC", "https://doi.org/10.1234/abc"),
            ("doi:10.1234/AbC", "http://dx.doi.org/10.1234/ABC"),
            ("10.1234/AbC", "https://DOI.ORG/10.1234%2FAbC"),
        ):
            with self.subTest(first=first, second=second):
                self.state["sources"][0]["locator"] = first
                self.state["sources"][1]["locator"] = second
                self.assertIn("duplicate_source", codes(audit(self.state, final=True)))

    def test_shared_artifacts_are_read_once_per_audit(self):
        self.state["sources"][1]["snapshot_file"] = "sources.txt"
        self.state["evidence"][0]["locator"] += "#已核对内容"
        opens = Counter()
        original_open = Path.open

        def tracked_open(path, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            if mode == "rb":
                opens[path.resolve()] += 1
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", tracked_open):
            report = audit(self.state, final=True, project_dir=self.workspace)
        self.assertEqual(report["errors"], [])
        self.assertEqual(opens[self.workspace / "sources.txt"], 1)
        self.assertEqual(sum(opens.values()), 4)

    def test_cached_artifact_still_checks_each_recorded_digest(self):
        self.state["sources"][1]["snapshot_sha256"] = "0" * 64
        report = audit(self.state, final=True)
        self.assertTrue(any(item["code"] == "stale_artifact" and "S1" in item["message"]
                            for item in report["errors"]))

    def test_symlink_loop_is_reported_without_crashing(self):
        loop = self.workspace / "proof-loop.md"
        loop.symlink_to(loop.name)
        self.state["evidence"][1]["locator"] = str(loop)
        self.assertIn("missing_artifact", codes(audit(self.state, final=True)))

    def test_cache_detects_file_changes_between_references(self):
        from audit_state import source_locator_key

        def change_before_next_reference(locator):
            if locator == self.state["sources"][1]["locator"]:
                (self.workspace / "sources.txt").write_text("变动后的合成文献快照", encoding="utf-8")
            return source_locator_key(locator)

        with patch("audit_state.source_locator_key", side_effect=change_before_next_reference):
            report = audit(self.state, final=True)
        self.assertTrue(any(item["code"] == "stale_artifact" and "S1" in item["message"]
                            for item in report["errors"]))

    def test_large_evidence_is_read_in_bounded_chunks(self):
        target = self.workspace / "proof.md"
        target.write_bytes(b"x" * (3 * 1024 * 1024 + 17))
        self.state["evidence"][1]["sha256"] = digest(target)
        original_open = Path.open
        reads = []

        class RecordingReader:
            def __init__(self, stream):
                self.stream = stream

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def read(self, size=-1):
                reads.append(size)
                return self.stream.read(size)

        @contextmanager
        def tracked_open(path, *args, **kwargs):
            with original_open(path, *args, **kwargs) as stream:
                yield RecordingReader(stream) if path == target else stream

        with patch.object(Path, "open", tracked_open):
            report = audit(self.state, final=True)
        self.assertEqual(report["errors"], [])
        self.assertGreater(len(reads), 1)
        self.assertTrue(all(0 < size <= 1024 * 1024 for size in reads), reads)

    def test_artifact_changed_during_read_is_rejected(self):
        target = self.workspace / "proof.md"
        original_open = Path.open

        class ChangingReader:
            def __init__(self, stream):
                self.stream = stream
                self.changed = False

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def read(self, size=-1):
                chunk = self.stream.read(size)
                if not self.changed:
                    self.changed = True
                    with original_open(target, "ab") as changed:
                        changed.write(b"changed-during-read")
                return chunk

        @contextmanager
        def tracked_open(path, *args, **kwargs):
            with original_open(path, *args, **kwargs) as stream:
                yield ChangingReader(stream) if path == target else stream

        with patch.object(Path, "open", tracked_open):
            report = audit(self.state, final=True)
        self.assertIn("artifact_changed_during_read", codes(report))


if __name__ == "__main__":
    unittest.main()
