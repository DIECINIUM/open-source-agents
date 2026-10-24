"""Offline regressions for source ingestion and the human approval gate."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from expense_review.agent import ExpenseAgent
from expense_review.connectors import import_keep
from expense_review.ledger import Ledger, guardrails
from expense_review.models import Extraction, Proposal, SourceNote


class ExpenseReviewChecks(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.ledger = Ledger(Path(self.folder.name) / "ledger.sqlite3")
        self.note = SourceNote(source="manual", source_id="synthetic", title="Lunch",
                               text="On 2026-10-20 I paid INR 250 for lunch.")
        self.proposal = Proposal(transaction_date="2026-10-20", amount="250", currency="INR",
                                 kind="spending", category="Food", counterparty="Cafe",
                                 reason="The source explicitly records a completed lunch payment.",
                                 evidence=self.note.text, confidence=0.95)

    def stage(self, note=None, proposal=None):
        note_id, _ = self.ledger.add_note(note or self.note)
        self.ledger.stage(note_id, [proposal or self.proposal], "One supported transaction.")
        return self.ledger.snapshot()["candidates"][0]["id"]

    def test_model_proposals_never_enter_totals_without_review(self):
        candidate = self.stage()
        self.assertEqual(self.ledger.monthly("2026-10")["approved_count"], 0)
        self.ledger.review(candidate, "approved", "Checked the original note.")
        result = self.ledger.monthly("2026-10")
        self.assertEqual(result["totals"]["spending"], "250")
        self.assertEqual(result["net_cashflow"], "-250")
        self.assertEqual(len(self.ledger.snapshot()["audit"]), 1)
        with self.assertRaisesRegex(ValueError, "already reviewed"):
            self.ledger.review(candidate, "approved", "Trying to approve twice.")

    def test_import_and_staging_are_idempotent(self):
        note_id, first = self.ledger.add_note(self.note)
        _, second = self.ledger.add_note(self.note)
        self.assertTrue(first)
        self.assertFalse(second)
        self.ledger.stage(note_id, [self.proposal], "One transaction.")
        self.ledger.stage(note_id, [self.proposal], "Same transaction.")
        self.assertEqual(len(self.ledger.snapshot()["candidates"]), 1)

    def test_blocking_guardrails_require_correction(self):
        for change, flag in [({"amount": "999"}, "amount_not_in_evidence"),
                             ({"currency": "USD"}, "unsupported_currency"),
                             ({"kind": "unknown"}, "unknown_direction"),
                             ({"evidence": "250 invented"}, "evidence_not_in_source")]:
            corrected = Proposal.model_validate({**self.proposal.model_dump(), **change})
            self.assertIn(flag, guardrails(corrected, self.note))
            candidate = self.stage()
            with self.assertRaisesRegex(ValueError, flag):
                self.ledger.review(candidate, "approved", "Checked the source document.", corrected)

    def test_same_date_and_amount_require_duplicate_confirmation(self):
        first = self.stage()
        self.ledger.review(first, "approved", "Checked first source.")
        other = self.note.model_copy(update={"source_id": "different-source"})
        self.stage(other)
        second = next(row["id"] for row in self.ledger.snapshot()["candidates"] if row["status"] == "pending")
        with self.assertRaisesRegex(ValueError, "Possible duplicate"):
            self.ledger.review(second, "approved", "Checked second source.")
        self.ledger.review(second, "approved", "Confirmed a distinct payment.", confirm_duplicate=True)
        self.assertEqual(self.ledger.monthly("2026-10")["approved_count"], 2)

    def test_lending_and_borrowing_are_not_expense_categories(self):
        lending = Proposal.model_validate({**self.proposal.model_dump(), "kind": "lending"})
        candidate = self.stage(proposal=lending)
        self.ledger.review(candidate, "approved", "Verified the lending transaction.")
        result = self.ledger.monthly("2026-10")
        self.assertEqual(result["totals"]["lending"], "250")
        self.assertEqual(result["totals"]["spending"], "0")
        self.assertEqual(result["categories"], {})
        borrowing = Proposal.model_validate({**self.proposal.model_dump(), "kind": "borrowing", "amount": "500",
                                            "evidence": "Received INR 500 on 2026-10-20 as a loan."})
        other = self.note.model_copy(update={"source_id": "loan", "text": borrowing.evidence})
        self.stage(other, borrowing)
        candidate = next(row["id"] for row in self.ledger.snapshot()["candidates"] if row["status"] == "pending")
        self.ledger.review(candidate, "approved", "Verified the borrowing transaction.")
        self.assertEqual(self.ledger.monthly("2026-10")["net_cashflow"], "250")

    def test_keep_checklists_and_schema_validation(self):
        notes = import_keep({"title": "Transactions", "textContent": "", "listContent": [{"text": self.note.text}]})
        self.assertEqual(notes[0].text, self.note.text)
        self.assertEqual(import_keep({"isTrashed": True}), [])
        with self.assertRaises(ValidationError):
            Proposal.model_validate({**self.proposal.model_dump(), "amount": "-1"})
        with self.assertRaises(ValidationError):
            Extraction.model_validate({"transactions": [], "explanation": "", "approved": True})

    def test_bad_model_output_stays_visible_as_error(self):
        class InvalidExtractor:
            async def extract(self, note):
                raise ValueError("Invalid schema")

        agent = ExpenseAgent(self.ledger, InvalidExtractor())
        agent.ingest([self.note])
        result = asyncio.run(agent.reason())
        self.assertEqual(result["errors"], 1)
        self.assertEqual(self.ledger.snapshot()["notes"][0]["state"], "error")
        self.assertEqual(self.ledger.monthly("2026-10")["approved_count"], 0)


if __name__ == "__main__":
    unittest.main()