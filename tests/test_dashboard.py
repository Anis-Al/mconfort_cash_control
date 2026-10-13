from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CashControlCase


@tagged('post_install', '-at_install')
class TestDashboard(CashControlCase):
    """Data behind the OWL dashboard (static/src/dashboard/): cash.control.day.get_dashboard_data()."""

    def test_kpis(self):
        day = self._open_first_day(100)
        self._pay(300, self.seller)
        self._pay(20, self.seller, payment_type='outbound')
        self._pay(50, self.seller).with_user(self.controller).action_cancel()
        self._deposit([(self._make_order(), 250)]).action_declare()  # stays to verify
        day.with_user(self.seller).write({'counted_amount': 120, 'closing_note': 'short'})
        day.with_user(self.seller).action_close()  # theoretical 100 + 300 - 20 - 250 = 130 -> -10

        Day = self.Day.with_user(self.controller)
        data = Day.get_dashboard_data('7')
        self.assertIsNone(data['drawer'], "no open day")
        kpis = data['kpis']
        self.assertEqual(kpis['closed_days']['count'], 1)
        self.assertEqual((kpis['days']['count'], kpis['days']['amount']), (1, -10))
        self.assertEqual(kpis['payments']['amount'], 280)
        self.assertEqual(kpis['refunds']['amount'], 20)
        self.assertEqual((kpis['cancelled']['count'], kpis['cancelled']['amount']), (1, 50))
        self.assertEqual((kpis['deposits_to_verify']['count'], kpis['deposits_to_verify']['amount']), (1, 250))

        action = Day.get_dashboard_action('cancelled', '7')
        self.assertEqual(action['res_model'], 'account.payment')
        self.assertEqual(self.env['account.payment'].search_count(action['domain']), 1)

        self.Day.with_user(self.seller).create({})
        self.assertEqual(Day.get_dashboard_data('7')['drawer'], 120)

    def test_seller_gets_the_drawer_only(self):
        """The dashboard is the app's home page for everyone, but the KPIs are for controllers."""
        self._open_first_day(100)
        data = self.Day.with_user(self.seller).get_dashboard_data('30')
        self.assertEqual((data['drawer'], data['is_controller'], data['kpis']), (100, False, {}))
        with self.assertRaises(AccessError):
            self.Day.with_user(self.seller).get_dashboard_action('days', '30')

    def test_controller_menus_hide_seller_entries(self):
        Menu = self.env['ir.ui.menu']
        ref = lambda xmlid: self.env.ref(f'mconfort_cash_control.{xmlid}').id  # noqa: E731
        seller_menus = Menu.with_user(self.seller).load_menus(False)
        controller_menus = Menu.with_user(self.controller).load_menus(False)
        for xmlid in ('menu_my_cash_day', 'menu_cash_control_movement', 'menu_cash_safe_deposit_new'):
            self.assertIn(ref(xmlid), seller_menus)
            self.assertNotIn(ref(xmlid), controller_menus)
        for xmlid in ('menu_cash_control_dashboard', 'menu_cash_safe_deposit_to_verify', 'menu_card_control'):
            self.assertIn(ref(xmlid), controller_menus)
        self.assertIn(ref('menu_cash_control_dashboard'), seller_menus, "the home page is for everyone")

    def test_outsiders_get_nothing(self):
        outsider = self.env['res.users'].create({'name': 'No Sales', 'login': 'cc_outsider'})
        with self.assertRaises(AccessError):
            self.Day.with_user(outsider).get_dashboard_data('30')
