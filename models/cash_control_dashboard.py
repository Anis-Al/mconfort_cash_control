from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .cash_control_day import CONTROLLER_GROUP, VALIDATED_PAYMENT_STATES

SELLER_GROUP = 'sales_team.group_sale_salesman'

# Card key -> measure summed next to the count (None: count only).
DASHBOARD_MEASURES = {
    'closed_days': None,
    'days': 'difference',
    'payments': 'amount_company_currency_signed',
    'refunds': 'amount_company_currency_signed',
    'cancelled': 'amount',
    'deposits_to_verify': 'amount_declared',
    'deposit_difference': 'difference',
    'cards': 'difference',
}


class CashControlDay(models.Model):
    """Data for the controller dashboard (OWL client action static/src/dashboard/, no model of its own)."""
    _inherit = 'cash.control.day'

    @api.model
    def _dashboard_domain(self, key, period):
        """(model, domain) behind each card. 'Deposits to verify' ignores the period: pending is pending."""
        since = fields.Date.context_today(self) - timedelta(days=int(period) - 1) if period != 'all' else None

        def dated(field, domain):
            return domain + [(field, '>=', since)] if since else domain

        cash = [('cash_day_id', '!=', False)]
        return {
            'closed_days': ('cash.control.day', dated('date', [('state', '=', 'closed')])),
            'days': ('cash.control.day', dated('date', [('state', '=', 'closed'), ('difference', '!=', 0)])),
            'payments': ('account.payment', dated('date', cash + [('state', 'in', VALIDATED_PAYMENT_STATES)])),
            'refunds': ('account.payment', dated('date', cash + [
                ('payment_type', '=', 'outbound'), ('state', 'in', VALIDATED_PAYMENT_STATES)])),
            'cancelled': ('account.payment', dated('date', cash + [('state', '=', 'canceled')])),
            'deposits_to_verify': ('cash.safe.deposit', [('state', '=', 'declared')]),
            'deposit_difference': ('cash.safe.deposit', dated('day_id.date', [
                ('state', '=', 'verified'), ('difference', '!=', 0)])),
            'cards': ('card.control', dated('date', [('state', '=', 'to_check')])),
        }[key]

    # Kept apart from _dashboard_domain(): mixing _() calls with domain strings confused the term extractor.
    @api.model
    def _dashboard_title(self, key):
        return {
            'closed_days': _("Closed Cash Days"),
            'days': _("Cash Days with a Difference"),
            'payments': _("Cash Payments"),
            'refunds': _("Cash Refunds and Payouts"),
            'cancelled': _("Cancelled Cash Payments"),
            'deposits_to_verify': _("Deposits to Verify"),
            'deposit_difference': _("Deposits with a Difference"),
            'cards': _("Card Controls to Check"),
        }[key]

    @api.model
    def _check_dashboard_access(self, period):
        if not self.env.user.has_group(CONTROLLER_GROUP):
            raise AccessError(_("The cash control dashboard is for controllers."))
        if period not in ('7', '30', '90', 'all'):
            raise ValueError(period)

    @api.model
    def get_dashboard_data(self, period='30'):
        """Home page of the app. Sellers get the drawer only; controllers also get the KPIs.
        Totals as the current user (record rules apply, no sudo)."""
        if not self.env.user.has_group(SELLER_GROUP):
            raise AccessError(_("Cash control is for sellers and controllers."))
        day = self._open_day(self.env.company)
        data = {
            'currency_id': self.env.company.currency_id.id,
            'drawer': day.theoretical_amount if day else None,
            'is_controller': self.env.user.has_group(CONTROLLER_GROUP),
            'kpis': {},
        }
        if not data['is_controller']:
            return data
        self._check_dashboard_access(period)
        kpis = data['kpis']
        for key, measure in DASHBOARD_MEASURES.items():
            model, domain = self._dashboard_domain(key, period)
            aggregates = ['__count'] + ([f'{measure}:sum'] if measure else [])
            [row] = self.env[model]._read_group(domain, aggregates=aggregates)
            kpis[key] = {'count': row[0], 'amount': (row[1] or 0.0) if measure else 0.0}
        kpis['refunds']['amount'] = -kpis['refunds']['amount']
        return data

    @api.model
    def get_dashboard_action(self, key, period='30'):
        self._check_dashboard_access(period)
        model, domain = self._dashboard_domain(key, period)
        return {
            'type': 'ir.actions.act_window',
            'name': self._dashboard_title(key),
            'res_model': model,
            'domain': domain,
            'views': [(False, 'list'), (False, 'form')],
            'context': {'create': False},
        }
