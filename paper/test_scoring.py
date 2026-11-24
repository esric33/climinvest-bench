"""Counterfactual checks of the prospective manuscript scoring policy."""

from copy import deepcopy
import unittest

from paper.scoring import rescore_report


BASELINE = """# Example

## A

| Indicator | Value |
| --- | --- |
| Source | [2 MW](dt.capacity) |
| Generation | [10 MWh](calc.generation) |

Generation is [10 MWh](calc.generation).

## B

### Interpretation

Unchanged discussion.
"""


def gold_fixture():
    return {
        "gold_sha256": "frozen-test-gold",
        "structure": {"sections": [
            {"id": "a", "title": "A", "components": [
                {"id": "a.table", "kind": "table", "headers": ["Indicator", "Value"]},
                {"id": "a.text", "kind": "llm"},
            ]},
            {"id": "b", "title": "B", "components": [
                {"id": "b.text", "kind": "llm", "subsection_id": "b.interpretation"},
            ], "subsections": [{"id": "b.interpretation", "title": "Interpretation"}]},
        ]},
        "evaluation_contract": {
            "expected_title": "Example", "section_id_map": {"a": "a", "b": "b"},
            "table_ids_by_section": {"a": ["a.table"], "b": []},
            "calculation_table_ids": ["a.table"],
        },
        "resolved": {
            "required_missing_targets": [],
            "tables": {"a.table": {
                "section_id": "a", "headers": ["Indicator", "Value"],
                "rows": [["Source", "[2 MW](dt.capacity)"],
                         ["Generation", "[10 MWh](calc.generation)"]],
            }},
        },
        "llm_obligations": [{
            "component_id": "a.text", "section_id": "a", "allowed_citation_ids": ["calc.generation"],
            "obligations": [{"id": "generation", "kind": "node_claim", "node_id": "calc.generation",
                "require_value": True, "expected_state": {"status": "available", "value": 10, "unit": "MWh"},
                "expected_labels": ["10 MWh"], "required_target_groups": [["calc.generation"]]}],
        }],
    }


class RevisedMetricTests(unittest.TestCase):
    def setUp(self):
        self.gold = gold_fixture()

    def score(self, text=BASELINE, **kwargs):
        return rescore_report(text, self.gold, **kwargs)

    def test_exact_report_scores_one_without_mutating_frozen_gold(self):
        before = deepcopy(self.gold)
        result = self.score()
        self.assertEqual(self.gold, before)
        self.assertTrue(all(item["score"] == 1 for item in result["components"].values()))
        self.assertFalse(result["details"]["source_equivalence"])
        self.assertEqual(result["details"]["semantic_judge_calls"], 0)

    def test_title_contributes_exactly_one_quarter(self):
        result = self.score(BASELINE.replace("# Example", "# Incorrect", 1))
        self.assertEqual(result["components"]["structure"]["score"], .75)
        self.assertAlmostEqual(result["details"]["historical_helper_scores"]["structure"], .95)

    def test_table_header_contributes_exactly_one_quarter(self):
        result = self.score(BASELINE.replace("| Indicator | Value |", "| Wrong | Value |"))
        self.assertEqual(result["components"]["tables"]["score"], .75)
        self.assertAlmostEqual(result["details"]["historical_helper_scores"]["tables"], .8)

    def test_source_value_error_does_not_reduce_calculation_score(self):
        result = self.score(BASELINE.replace("[2 MW]", "[200 MW]"))
        self.assertEqual(result["components"]["calculations"]["score"], 1)
        self.assertLess(result["components"]["tables"]["score"], 1)
        self.assertLess(result["details"]["historical_helper_scores"]["calculations"], 1)

    def test_prose_calculation_error_is_counted_separately(self):
        result = self.score(BASELINE.replace("Generation is [10 MWh]", "Generation is [99 MWh]"))
        calc = result["components"]["calculations"]
        self.assertEqual(calc["table_occurrence_count"], 1)
        self.assertEqual(calc["prose_occurrence_count"], 1)
        self.assertEqual(calc["table_value_accuracy"], .5)
        self.assertEqual(calc["table_unit_accuracy"], 1)
        self.assertEqual(calc["score"], .75)
        self.assertEqual(result["components"]["tables"]["score"], 1)

    def test_wrong_unit_is_independent_of_correct_numeric_value(self):
        result = self.score(BASELINE.replace("10 MWh", "10 kWh"))
        calc = result["components"]["calculations"]
        self.assertEqual(calc["table_value_accuracy"], 1)
        self.assertEqual(calc["table_unit_accuracy"], 0)
        self.assertEqual(calc["score"], .5)

    def test_absent_prose_fails_its_expected_calculation_occurrence(self):
        result = self.score(BASELINE.replace("Generation is [10 MWh](calc.generation).", "No numeric result."))
        self.assertEqual(result["components"]["calculations"]["score"], .5)

    def test_interpretation_only_obligation_does_not_require_a_value(self):
        self.gold["llm_obligations"][0]["obligations"][0]["require_value"] = False
        result = self.score(BASELINE.replace("Generation is [10 MWh](calc.generation).", "No numeric result."))
        self.assertEqual(result["components"]["calculations"]["score"], 1)
        self.assertEqual(result["components"]["calculations"]["prose_occurrence_count"], 0)

    def test_repeated_required_occurrences_consume_distinct_uses(self):
        self.gold["resolved"]["tables"]["a.table"]["rows"].append(["Generation again", "[10 MWh](calc.generation)"])
        result = self.score()
        self.assertAlmostEqual(result["components"]["calculations"]["score"], 2/3)

    def test_first_use_is_not_replaced_by_a_later_correct_use(self):
        result = self.score(BASELINE.replace("Generation is [10 MWh](calc.generation).",
                           "Generation is [99 MWh](calc.generation), later [10 MWh](calc.generation)."))
        self.assertEqual(result["components"]["calculations"]["score"], .75)

    def test_label_errors_do_not_turn_into_calculation_value_errors(self):
        result = self.score(BASELINE.replace("| Generation |", "| Something else |"))
        self.assertEqual(result["components"]["calculations"]["score"], 1)
        self.assertLess(result["components"]["tables"]["score"], 1)

    def test_available_scalar_text_calculations_are_compared(self):
        row = self.gold["resolved"]["tables"]["a.table"]["rows"][1]
        row[1] = "[reconciled](calc.generation)"
        obligation = self.gold["llm_obligations"][0]["obligations"][0]
        obligation["expected_state"] = {"status": "available", "value": "reconciled", "unit": None}
        obligation["expected_labels"] = ["reconciled"]
        text = BASELINE.replace("10 MWh", "reconciled")
        self.assertEqual(self.score(text)["components"]["calculations"]["score"], 1)
        self.assertEqual(self.score(text.replace("reconciled", "unreconciled"))["components"]["calculations"]["score"], 0)

    def test_missing_result_requires_missing_marker_not_numeric_result(self):
        row = self.gold["resolved"]["tables"]["a.table"]["rows"][1]
        row[1] = "[missing](missing.calc.generation)"
        obligation = self.gold["llm_obligations"][0]["obligations"][0]
        obligation["expected_state"] = {"status": "missing_dependency", "value": None}
        obligation["expected_labels"] = ["missing"]
        obligation["required_target_groups"] = [["missing.calc.generation"]]
        self.gold["resolved"]["required_missing_targets"] = ["missing.calc.generation"]
        text = BASELINE.replace("[10 MWh](calc.generation)", "[missing](missing.calc.generation)")
        self.assertEqual(self.score(text)["components"]["calculations"]["score"], 1)
        self.assertEqual(self.score(text.replace("missing.calc.generation", "calc.generation"))["components"]["calculations"]["score"], 0)

    def test_nonscalar_prose_output_excluded_and_recorded(self):
        obligation = self.gold["llm_obligations"][0]["obligations"][0]
        obligation["expected_state"]["value"] = [{"id": "record.1"}]
        obligation["expected_labels"] = ["Record one"]
        calc = self.score()["components"]["calculations"]
        self.assertEqual(calc["prose_occurrence_count"], 0)
        self.assertEqual(calc["excluded_prose_obligations"][0]["reason"], "available_nonscalar_result")

    def test_literal_calculation_target_matching(self):
        result = self.score(BASELINE.replace("calc.generation", "calc.equivalent_generation"))
        self.assertEqual(result["components"]["calculations"]["score"], 0)
        self.assertLess(result["components"]["citations"]["score"], 1)

    def test_selected_set_membership_and_order_have_equal_weight(self):
        component = self.gold["llm_obligations"][0]
        component["allowed_citation_ids"].extend(["dt.r1", "dt.r2"])
        component["obligations"].append({
            "id": "selected", "kind": "selected_set", "require_value": False,
            "required_target_groups": [["dt.r1"], ["dt.r2"]],
            "universe_record_ids": ["dt.r1", "dt.r2"], "expected_record_ids": ["dt.r1", "dt.r2"],
            "universe_members": [{"record_id": "dt.r1", "citation_ids": ["dt.r1"]},
                                 {"record_id": "dt.r2", "citation_ids": ["dt.r2"]}],
        })
        text = BASELINE.replace("Generation is [10 MWh](calc.generation).",
                                "Generation is [10 MWh](calc.generation). [Two](dt.r2), [One](dt.r1).")
        result = self.score(text)
        prose = result["components"]["citations"]["prose_obligations"]
        self.assertEqual(prose["selected_set_score"], .75)
        self.assertEqual(prose["score"], .9375)
        self.assertEqual(result["components"]["citations"]["score"], .96875)

    def test_maintenance_any_present_affected_change_counts_even_if_wrong(self):
        text = BASELINE.replace("Generation is", "Incorrectly asserted generation is")
        update = self.score(text, canonical_markdown=BASELINE, affected_section_ids={"a"})["update"]
        self.assertEqual(update["affected_section_change_rate"], 1)
        self.assertEqual(update["unaffected_section_preservation"], 1)

    def test_maintenance_line_displacement_does_not_change_preservation(self):
        text = BASELINE.replace("Generation is", "Added explanation.\n\nGeneration is")
        update = self.score(text, canonical_markdown=BASELINE, affected_section_ids={"a"})["update"]
        self.assertEqual(update["affected_section_change_rate"], 1)
        self.assertEqual(update["unaffected_section_preservation"], 1)

    def test_maintenance_omitted_sections_receive_zero(self):
        missing_a = "# Example\n\n## B" + BASELINE.split("## B", 1)[1]
        update = self.score(missing_a, canonical_markdown=BASELINE, affected_section_ids={"a"})["update"]
        self.assertEqual(update["affected_section_change_rate"], 0)
        missing_b = BASELINE.split("## B", 1)[0]
        update = self.score(missing_b, canonical_markdown=BASELINE, affected_section_ids={"a"})["update"]
        self.assertEqual(update["unaffected_section_preservation"], 0)

    def test_maintenance_empty_sets_score_one_and_missing_baseline_rejected(self):
        update = self.score(canonical_markdown=BASELINE, affected_section_ids=set())["update"]
        self.assertEqual(update["affected_section_change_rate"], 1)
        with self.assertRaisesRegex(ValueError, "Canonical baseline lacks"):
            self.score(canonical_markdown="# Example", affected_section_ids={"a"})


if __name__ == "__main__":
    unittest.main()
