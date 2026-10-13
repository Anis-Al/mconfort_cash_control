from odoo import Command
from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import CashControlCase

HIDDEN = ('declared_at', 'verified_at', 'create_date', 'write_date')


@tagged('post_install', '-at_install')
class TestSafeDeposit(CashControlCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.order = cls._make_order()

    def test_deposit_verify_difference(self):
        """Spec Phase 3: deposit of 250 on an order, counted 230 -> difference -20;
        verifying changes no cash day amount."""
        day = self._open_first_day(300)
        deposit = self._deposit([(self.order, 250)])
        self.assertFalse(deposit.name, "the number is given at declaration")
        deposit.action_declare()
        self.assertRecordValues(deposit, [{
            'state': 'declared', 'day_id': day.id, 'amount_declared': 250, 'user_id': self.seller.id}])
        self.assertTrue(deposit.name.startswith('DEP/'))
        self.assertTrue(deposit.with_user(self.controller).declared_at)
        before = day.theoretical_amount
        self.assertEqual(before, 50)

        controller_deposit = deposit.with_user(self.controller)
        controller_deposit.amount_counted = 230
        controller_deposit.action_verify()
        self.assertRecordValues(deposit, [{
            'state': 'verified', 'difference': -20, 'verified_by': self.controller.id}])
        self.assertTrue(deposit.with_user(self.controller).verified_at)
        self.assertEqual(day.theoretical_amount, before, "verification never moves a balance")
        self.assertEqual(day.deposit_amount, 250, "the declared amount leaves the drawer, not the counted one")

    def test_seller_cannot_see_timestamps(self):
        """Spec Phase 3: not by form, list, export or RPC (read, search_read, domain, group by)."""
        self._open_first_day()
        deposit = self._deposit([(self.order, 100)])
        deposit.action_declare()
        Deposit, Line = self.Deposit.with_user(self.seller), self.env['cash.safe.deposit.line'].with_user(self.seller)

        for model, record in ((Deposit, deposit.with_user(self.seller)), (Line, deposit.line_ids.with_user(self.seller))):
            hidden = [f for f in HIDDEN if f in model._fields]
            self.assertFalse(set(hidden) & set(model.fields_get()), "fields_get must not list them")
            for view_type in ('form', 'list'):
                arch = model.get_views([(False, view_type)])['views'][view_type]['arch']
                for fname in hidden:
                    self.assertNotIn(f'name="{fname}"', arch, f"{model._name} {view_type} shows {fname}")
            for fname in hidden:
                with self.assertRaises(AccessError):
                    record.read([fname])
                with self.assertRaises(AccessError):
                    model.search_read([], [fname])
                with self.assertRaises(AccessError):
                    model.search([(fname, '!=', False)])
                with self.assertRaises(AccessError):
                    model.formatted_read_group([], groupby=[fname])
                with self.assertRaises(AccessError):
                    record.export_data([fname])
            self.assertFalse(set(hidden) & set(record.read()[0]), "a bare read() must skip them")

        # The controller sees them.
        self.assertTrue(deposit.with_user(self.controller).declared_at)

    def test_rules(self):
        self._open_first_day()
        order_2 = self._make_order()
        with self.assertRaises(UserError):
            self._deposit([]).action_declare()
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self._deposit([(self.order, 10), (self.order, 20)])
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self._deposit([(self.order, -5)])

        deposit = self._deposit([(self.order, 100)])
        deposit.write({'line_ids': [Command.create({'sale_order_id': order_2.id, 'amount': 20})]})
        self.assertEqual(deposit.amount_declared, 120, "lines are editable while draft")
        with self.assertRaises(UserError):
            deposit.with_user(self.seller).write({'state': 'verified'})
        with self.assertRaises(UserError):  # no backdating: the write whitelist refuses it
            deposit.with_user(self.seller).write({'declared_at': '2020-01-01 00:00:00'})
        deposit.with_user(self.seller).action_declare()

        seller_deposit = deposit.with_user(self.seller)
        line = seller_deposit.line_ids[0]
        with self.assertRaises(UserError):
            line.write({'amount': 1})
        with self.assertRaises(UserError):
            line.unlink()
        with self.assertRaises(UserError):
            seller_deposit.write({'line_ids': [Command.create({'sale_order_id': self.order.id, 'amount': 1})]})
        with self.assertRaises(UserError):
            seller_deposit.write({'amount_counted': 120})
        with self.assertRaises(AccessError):
            seller_deposit.action_verify()
        with self.assertRaises(UserError):
            seller_deposit.unlink()

        controller_deposit = deposit.with_user(self.controller)
        with self.assertRaises(UserError):
            controller_deposit.action_verify()  # nothing typed yet
        controller_deposit.write({'amount_counted': 120})
        controller_deposit.action_verify()
        with self.assertRaises(UserError):
            controller_deposit.write({'amount_counted': 0})
        with self.assertRaises(UserError):
            controller_deposit.unlink()

    def test_draft_deposit_can_be_deleted(self):
        deposit = self._deposit([(self.order, 100)])
        deposit.with_user(self.seller).unlink()
        self.assertFalse(deposit.exists())

    def test_declare_needs_open_day(self):
        deposit = self._deposit([(self.order, 100)])
        with self.assertRaises(UserError):
            deposit.action_declare()
