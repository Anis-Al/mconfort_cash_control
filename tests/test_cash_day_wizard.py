from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CashControlCase


@tagged('post_install', '-at_install')
class TestCashDayWizard(CashControlCase):

    def _wizard(self, user):
        action = self.Day.with_user(user).action_my_cash_day()
        self.assertEqual((action['res_model'], action['target']), ('cash.control.day.wizard', 'new'))
        return self.env[action['res_model']].with_user(user).browse(action['res_id'])

    def test_full_day(self):
        # First day: only a controller can open it, with the typed amount.
        wizard = self._wizard(self.seller)
        self.assertRecordValues(wizard, [{'day_id': False, 'can_edit_opening': False}])
        with self.assertRaises(UserError):
            wizard.action_open_day()
        wizard = self._wizard(self.controller)
        self.assertTrue(wizard.can_edit_opening)
        wizard.opening_amount = 100
        wizard.action_open_day()
        wizard.invalidate_recordset()  # the client reloads the pop-up; here the cache still holds "no day"
        day = wizard.day_id
        self.assertEqual(day.opening_amount, 100)

        # The seller works the day from the pop-up.
        wizard = self._wizard(self.seller)
        self.assertEqual(wizard.day_id, day)
        self._pay(300, self.seller)
        wizard.write({'movement_type': 'out', 'movement_amount': 30, 'movement_reason': 'Change for the bank'})
        wizard.action_add_movement()
        self.assertRecordValues(wizard, [{'movement_amount': 0, 'movement_reason': False, 'theoretical_amount': 370}])
        wizard.write({'movement_amount': 0, 'movement_reason': 'x'})
        with self.assertRaises(UserError):
            wizard.action_add_movement()

        wizard.counted_amount = 360
        self.assertEqual(wizard.count_gap, -10)
        with self.assertRaises(UserError):
            wizard.action_close_day()  # gap without a note
        wizard.closing_note = "10 missing"
        result = wizard.action_close_day()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(result['params']['type'], 'warning')
        self.assertRecordValues(day, [{'state': 'closed', 'difference': -10, 'closed_by': self.seller.id}])

        # Next opening: the last count, whatever is typed.
        wizard = self._wizard(self.seller)
        self.assertRecordValues(wizard, [{'day_id': False, 'opening_amount': 360, 'can_edit_opening': False}])
        wizard.opening_amount = 999
        wizard.action_open_day()
        wizard.invalidate_recordset()
        self.assertEqual(wizard.day_id.opening_amount, 360)
