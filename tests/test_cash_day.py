from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CashControlCase


@tagged('post_install', '-at_install')
class TestCashDay(CashControlCase):

    def test_theoretical_count_and_next_opening(self):
        """Spec Phase 2: opening 100, cash payments 300, deposits 250 -> theoretical 150;
        counted 120 -> difference -30, note required; the next day opens at 120."""
        day = self._open_first_day(100)
        self._pay(300, self.seller)
        self._deposit([(self._make_order(), 250)]).action_declare()
        self.assertRecordValues(day, [{'deposit_amount': 250, 'theoretical_amount': 150}])

        seller_day = day.with_user(self.seller)
        seller_day.counted_amount = 120
        self.assertEqual(seller_day.count_gap, -30, "the gap is shown live while counting")
        with self.assertRaises(UserError):
            seller_day.action_close()
        seller_day.closing_note = "30 missing, recounted twice"
        seller_day.action_close()
        self.assertRecordValues(day, [{
            'state': 'closed',
            'closing_theoretical_amount': 150,
            'theoretical_amount': 150,
            'difference': -30,
            'closed_by': self.seller.id,
        }])

        next_day = self.Day.with_user(self.seller).create({'opening_amount': 999})
        self.assertEqual(next_day.opening_amount, 120, "opening comes from the last count, not from the client")
        self.assertEqual(next_day.user_id, self.seller)

    def test_movements(self):
        day = self._open_first_day(100)
        self.Movement.with_user(self.seller).create({'type': 'in', 'amount': 20, 'reason': 'Change'})
        self.Movement.with_user(self.seller).create({'type': 'out', 'amount': 5, 'reason': 'Stamps'})
        self.assertRecordValues(day, [{'movement_in_amount': 20, 'movement_out_amount': 5, 'theoretical_amount': 115}])

    def test_refund_counts_as_cash_out(self):
        day = self._open_first_day(100)
        self._pay(40, self.seller, payment_type='outbound')
        self.assertRecordValues(day, [{'payment_out_amount': 40, 'theoretical_amount': 60}])

    def test_invoice_pay_wizard_links_the_day(self):
        """The wizard sets the payment state inside create(), before action_post."""
        day = self._open_first_day(0)
        invoice = self.env['account.move'].with_user(self.seller).create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_line_ids': [Command.create({'name': 'Sofa', 'quantity': 1, 'price_unit': 80, 'tax_ids': []})],
        })
        invoice.action_post()
        payment = self.env['account.payment.register'].with_user(self.seller).with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({'journal_id': self.cash_journal.id})._create_payments()
        self.assertEqual(payment.cash_day_id, day)
        self.assertEqual(day.theoretical_amount, 80)

    def test_cash_payment_refused_without_open_day(self):
        with self.assertRaises(UserError):
            self._pay(50, self.seller)
        bank_payment = self._pay(50, self.seller, journal=self.bank_journal)
        self.assertFalse(bank_payment.cash_day_id, "only the controlled cash journal needs a day")

    def test_closed_day_is_frozen(self):
        day = self._open_first_day(100)
        payment = self._pay(50, self.seller)
        day.with_user(self.seller).counted_amount = 150
        day.with_user(self.seller).action_close()
        payment.with_user(self.controller).action_draft()
        self.assertEqual(day.payment_in_amount, 0, "the breakdown stays live")
        self.assertEqual(day.theoretical_amount, 150, "the closing value is frozen")

    def test_first_day_needs_a_controller(self):
        with self.assertRaises(UserError):
            self.Day.with_user(self.seller).create({'opening_amount': 500})

    def test_one_open_day(self):
        self._open_first_day()
        with self.assertRaises(UserError):
            self.Day.with_user(self.controller).create({})

    def test_seller_locks(self):
        day = self._open_first_day()
        payment = self._pay(10, self.seller)
        self.assertEqual(payment.cash_day_id, day)
        movement = self.Movement.with_user(self.seller).create({'type': 'in', 'amount': 5, 'reason': 'Change'})
        self.assertEqual(movement.day_id, day)
        self.assertEqual(movement.user_id, self.seller)

        for vals in ({'opening_amount': 0}, {'state': 'closed'}, {'user_id': self.controller.id}):
            with self.assertRaises(UserError):
                day.with_user(self.seller).write(vals)
        with self.assertRaises(UserError):
            payment.with_user(self.seller).write({'cash_day_id': False})
        with self.assertRaises(UserError):
            movement.with_user(self.seller).write({'amount': 500})
        for user in (self.seller, self.controller):
            with self.assertRaises(AccessError):
                movement.with_user(user).unlink()
            with self.assertRaises(AccessError):
                day.with_user(user).unlink()

        day.with_user(self.seller).write({'counted_amount': 115})
        day.with_user(self.seller).action_close()
        with self.assertRaises(UserError):
            day.with_user(self.seller).write({'counted_amount': 0})
        with self.assertRaises(UserError):
            self.Movement.with_user(self.seller).create({'type': 'out', 'amount': 1, 'reason': 'No day'})
