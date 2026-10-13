from datetime import date

from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import CashControlCase

DAY = date(2026, 10, 1)


@tagged('post_install', '-at_install')
class TestCardControl(CashControlCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.card_journal = cls.bank_journal
        # Same setup as BNK3: manual payments hit the bank account and post as 'paid'.
        (cls.card_journal.inbound_payment_method_line_ids
         + cls.card_journal.outbound_payment_method_line_ids).payment_account_id = cls.card_journal.default_account_id
        cls.company.card_control_journal_ids = cls.card_journal
        cls.Control = cls.env['card.control'].with_user(cls.controller)

    def _card(self, amount, payment_type='inbound', day=DAY, **extra):
        return self._pay(amount, self.controller, payment_type=payment_type, journal=self.card_journal, date=day, **extra)

    def _control(self, *amounts, day=DAY):
        return self.Control.create({
            'date': day,
            **dict(zip(('amount_contactless', 'amount_immediate', 'amount_deferred_30',
                        'amount_deferred_60', 'amount_deferred_90'), amounts)),
        })

    def _odoo_3350(self):
        self._card(3000)
        self._card(500)
        self._card(150, payment_type='outbound')  # refund on card
        # Not counted: other day, other journal, draft, cancelled.
        self._card(999, day=date(2026, 10, 2))
        self._open_first_day()
        self._pay(888, self.controller, date=DAY)  # cash
        self.env['account.payment'].with_user(self.controller).create({
            'amount': 777, 'partner_id': self.partner.id, 'journal_id': self.card_journal.id, 'date': DAY})
        self._card(666).action_cancel()

    def test_matched(self):
        """Spec Phase 4: files 450 + 1200 + 700 + 500 + 500 = 3350 against Odoo 3350: matched."""
        self._odoo_3350()
        control = self._control(450, 1200, 700, 500, 500)
        self.assertRecordValues(control, [{'total_files': 3350, 'total_odoo': 3350, 'state': 'draft'}])
        control.action_validate()
        self.assertRecordValues(control, [{
            'state': 'matched', 'difference': 0, 'validated_total_odoo': 3350, 'user_id': self.controller.id}])
        self.assertTrue(control.validated_at)

    def test_to_check_and_frozen(self):
        """Spec Phase 4: files totalling 3250 against Odoo 3350: to_check, gap of 100."""
        self._odoo_3350()
        control = self._control(450, 1200, 700, 500, 400)
        control.action_validate()
        self.assertRecordValues(control, [{'state': 'to_check', 'total_files': 3250, 'difference': -100}])

        self._card(100)  # a late payment dated that day
        self.assertEqual(control.total_odoo, 3350, "frozen at validation")
        self.assertEqual(control._odoo_card_total(), 3450, "the live total moved (Phase 6 drift)")

    def test_method_line_filter(self):
        manual_in = self.card_journal.inbound_payment_method_line_ids[:1]
        card_line = manual_in.copy({'name': 'Carte bancaire'})
        self._card(300)
        self._card(200, payment_method_line_id=card_line.id)
        control = self._control(200)
        self.assertEqual(control.total_odoo, 500, "no method filter: the whole journal")
        self.company.card_control_method_line_ids = card_line
        control.invalidate_recordset(['total_odoo'])
        self.assertEqual(control.total_odoo, 200, "only the card method line")

    def test_access_and_locks(self):
        with self.assertRaises(AccessError):
            self.env['card.control'].with_user(self.seller).search([])
        with self.assertRaises(AccessError):
            self.env['card.control'].with_user(self.seller).create({'date': DAY})

        control = self.Control.create({'date': DAY, 'amount_immediate': 10, 'state': 'matched',
                                       'validated_total_odoo': 10, 'user_id': self.seller.id})
        self.assertRecordValues(control, [{'state': 'draft', 'validated_total_odoo': 0, 'user_id': False}])
        with self.assertRaises(UserError):
            control.write({'state': 'matched'})
        control.write({'amount_immediate': 20})
        control.action_validate()
        with self.assertRaises(UserError):
            control.write({'amount_immediate': 30})
        with self.assertRaises(UserError):
            control.unlink()
        with self.assertRaises(UserError):
            control.action_validate()
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.Control.create({'date': DAY})

    def test_draft_can_be_deleted(self):
        control = self._control(10)
        control.unlink()
        self.assertFalse(control.exists())
