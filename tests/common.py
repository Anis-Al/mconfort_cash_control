from odoo import Command
from odoo.tests import TransactionCase, new_test_user


class CashControlCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        # A fresh drawer, so the tests do not depend on days already open in the database.
        cls.cash_journal = cls.env['account.journal'].create({'name': 'Test Drawer', 'type': 'cash', 'code': 'TDRW'})
        # Same setup as the real drawer (CSH1): payments hit the cash account and post as 'paid'.
        (cls.cash_journal.inbound_payment_method_line_ids
         + cls.cash_journal.outbound_payment_method_line_ids).payment_account_id = cls.cash_journal.default_account_id
        cls.bank_journal = cls.env['account.journal'].create({'name': 'Test Bank', 'type': 'bank', 'code': 'TBNK'})
        cls.company.cash_control_journal_id = cls.cash_journal

        # allow_export on the seller makes the "hidden from export" checks meaningful.
        cls.seller = new_test_user(
            cls.env, 'cc_seller',
            groups='sales_team.group_sale_salesman,account.group_account_invoice,base.group_allow_export')
        cls.controller = new_test_user(
            cls.env, 'cc_controller', groups='sales_team.group_sale_manager,account.group_account_invoice')
        cls.partner = cls.env['res.partner'].create({'name': 'Cash Customer'})
        cls.product = cls.env['product.product'].create({'name': 'Sofa', 'list_price': 250})
        cls.Day = cls.env['cash.control.day']
        cls.Movement = cls.env['cash.control.movement']
        cls.Deposit = cls.env['cash.safe.deposit']

    def _pay(self, amount, user, payment_type='inbound', journal=None, **extra):
        payment = self.env['account.payment'].with_user(user).create({
            'payment_type': payment_type,
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': amount,
            'journal_id': (journal or self.cash_journal).id,
            **extra,
        })
        payment.action_post()
        return payment

    def _open_first_day(self, opening=100.0):
        return self.Day.with_user(self.controller).create({'opening_amount': opening})

    @classmethod
    def _make_order(cls):
        return cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'user_id': cls.seller.id,
            'order_line': [Command.create({'product_id': cls.product.id, 'product_uom_qty': 1})],
        })

    def _deposit(self, lines, user=None):
        """lines: [(order, amount)]"""
        return self.Deposit.with_user(user or self.seller).create({'line_ids': [
            Command.create({'sale_order_id': order.id, 'amount': amount}) for order, amount in lines
        ]})
