"""Field filling: render.fill(), render.fill_text() and render.placeholders()."""

import unittest

import render


class Fill(unittest.TestCase):

    def test_names_ignore_case(self):
        self.assertEqual(render.fill("{{Code}}/{{CODE}}", {"code": "A1"}, False), "A1/A1")
        self.assertEqual(render.fill("{{code}}", {"Code": "A1"}, False), "A1")

    def test_builtins(self):
        self.assertRegex(render.fill("{{Date}}", {}, False), r"^\d{4}-\d\d-\d\d$")
        self.assertRegex(render.fill("{{time}}", {}, False), r"^\d\d:\d\d$")
        self.assertRegex(render.fill("{{datetime}}", {}, False), r"^\d{4}-\d\d-\d\d \d\d:\d\d$")

    def test_record_overrides_builtin(self):
        self.assertEqual(render.fill("{{date}}", {"Date": "soon"}, False), "soon")

    def test_empty_and_missing_fields_fill_as_nothing(self):
        for keep in (True, False):   # preview and print alike
            with self.subTest(keep_missing=keep):
                self.assertEqual(render.fill("[{{a}}{{b}}]", {"a": ""}, keep), "[]")

    def test_chained_fields_expand(self):
        rec = {"sku": "P-{{item}}", "item": "42"}
        self.assertEqual(render.fill("{{sku}}", rec, False, chain={"SKU"}), "P-42")

    def test_unchained_values_are_used_as_written(self):
        # CSV cells are never expanded
        rec = {"sku": "P-{{item}}", "item": "42"}
        self.assertEqual(render.fill("{{sku}}", rec, False), "P-{{item}}")

    def test_loop_is_reported_once(self):
        rec = {"a": "x{{b}}", "b": "y{{a}}"}
        warnings = []
        preview = render.fill("{{a}}", rec, True, chain={"a", "b"}, warnings=warnings)
        printed = render.fill("{{a}}", rec, False, chain={"a", "b"}, warnings=warnings)
        self.assertEqual(preview, "xy{{a}}")   # the preview keeps the looping tag
        self.assertEqual(printed, "xy")
        self.assertEqual(warnings, ["Fields refer to each other in a loop: {{a}} → {{b}} → {{a}}"])


class FillText(unittest.TestCase):

    def fill(self, template, keep_missing=False, **record):
        return render.fill_text(template, record, keep_missing)

    def test_all_fields_filled(self):
        self.assertEqual(self.fill("{{first}} {{last}}", first="Ada", last="Lovelace"),
                         ("Ada Lovelace", False))

    def test_spaces_beside_an_empty_field_go_with_it(self):
        self.assertEqual(self.fill("{{first}} {{mid}} {{last}}", first="Ada", last="Lovelace"),
                         ("Ada Lovelace", False))
        self.assertEqual(self.fill("{{first}} {{last}}", first="Ada"), ("Ada", False))
        self.assertEqual(self.fill("{{first}} {{last}}", last="Lovelace"), ("Lovelace", False))

    def test_line_left_blank_is_removed(self):
        self.assertEqual(self.fill("{{a}}\n{{b}}\n{{c}}", a="A", c="C"), ("A\nC", False))

    def test_typed_blank_lines_stay(self):
        self.assertEqual(self.fill("{{a}}\n\nfixed", a="A"), ("A\n\nfixed", False))

    def test_text_without_fields_is_kept(self):
        self.assertEqual(self.fill("Hello"), ("Hello", False))

    def test_hidden_when_every_field_is_empty(self):
        # Fixed text around the fields goes too, in the preview and in print
        for keep in (True, False):
            with self.subTest(keep_missing=keep):
                self.assertEqual(self.fill("SKU: {{code}}", keep), ("", True))
                self.assertEqual(self.fill("Name\n{{name}}", keep, name=""), ("", True))


class Placeholders(unittest.TestCase):

    def test_listed_once_as_first_spelled(self):
        layout = {"elements": [
            {"type": "text", "text": "{{Title}} {{ title }}"},
            {"type": "qr", "data": "{{Code}}"},
            {"type": "text", "text": "{{CODE}} {{date}}"},
        ]}
        self.assertEqual(render.placeholders(layout), ["Title", "Code", "date"])
