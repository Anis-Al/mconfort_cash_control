from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .cash_control_day import VALIDATED_PAYMENT_STATES

TYPED_FIELDS = (
    'amount_contactless', 'amount_immediate',
    'amount_deferred_30', 'amount_deferred_60', 'amount_deferred_90',
)


class CardControl(models.Model):
    """Controller-only (no seller ACL): bank card totals typed by the owner vs Odoo."""
    _name = 'card.control'
    _description = "Card Control"
    _order = 'date desc'
    _rec_name = 'date'

    company_id = fields.Many2one(
        'res.company', required=True, readonly=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date = fields.Date(
        required=True, default=fields.Date.context_today,
        help="Day controlled: Odoo counts the card payments dated that day.")
    state = fields.Selection(
        [('draft', "Draft"), ('matched', "Matched"), ('to_check', "To Check")],
        default='draft', required=True, readonly=True)

    # Typed from the bank files. Not constrained to be positive: a file total can be net of refunds.
    amount_contactless = fields.Monetary(string="Contactless")
    amount_immediate = fields.Monetary(string="Immediate")
    amount_deferred_30 = fields.Monetary(string="Deferred 30 Days")
    amount_deferred_60 = fields.Monetary(string="Deferred 60 Days")
    amount_deferred_90 = fields.Monetary(string="Deferred 90 Days")
    total_files = fields.Monetary(compute='_compute_total_files', store=True)

    total_odoo = fields.Monetary(
        compute='_compute_total_odoo',
        help="Validated card payments of the day, inbound minus outbound. Live while draft, frozen at validation.")
    validated_total_odoo = fields.Monetary(string="Odoo Total at Validation", readonly=True)
    difference = fields.Monetary(
        compute='_compute_difference', store=True,
        help="Bank files total minus Odoo total, once validated.")

    # Set by the server at validation.
    user_id = fields.Many2one('res.users', string="Validated By", readonly=True)
    validated_at = fields.Datetime(readonly=True)

    _date_unique = models.Constraint(
        'UNIQUE(company_id, date)', "This day already has a card control.")

    # -------------------------------------------------------------------------
    # COMPUTE
    # -------------------------------------------------------------------------

    @api.depends(*TYPED_FIELDS)
    def _compute_total_files(self):
        for control in self:
            control.total_files = sum(control[fname] for fname in TYPED_FIELDS)

    @api.depends('state', 'date', 'validated_total_odoo')
    def _compute_total_odoo(self):
        for control in self:
            control.total_odoo = (
                control._odoo_card_total() if control.state == 'draft' else control.validated_total_odoo)

    @api.depends('state', 'total_files', 'validated_total_odoo')
    def _compute_difference(self):
        for control in self:
            control.difference = (
                control.total_files - control.validated_total_odoo if control.state != 'draft' else 0.0)

    def _card_payment_domain(self):
        self.ensure_one()
        company = self.company_id
        domain = [
            ('company_id', '=', company.id),
            ('journal_id', 'in', company.card_control_journal_ids.ids),
            ('state', 'in', VALIDATED_PAYMENT_STATES),
            ('date', '=', self.date),
        ]
        if company.card_control_method_line_ids:
            domain.append(('payment_method_line_id', 'in', company.card_control_method_line_ids.ids))
        return domain

    def _odoo_card_total(self):
        self.ensure_one()
        if not self.date or not self.company_id.card_control_journal_ids:
            return 0.0
        [(total,)] = self.env['account.payment']._read_group(
            self._card_payment_domain(), aggregates=['amount_company_currency_signed:sum'])
        return total or 0.0

    # -------------------------------------------------------------------------
    # CRUD + LOCKS
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        # Only the day and the five typed totals come from the client.
        return super().create([
            {
                **{key: vals[key] for key in ('date', *TYPED_FIELDS) if key in vals},
                'company_id': self.env.company.id,
            }
            for vals in vals_list
        ])

    def write(self, vals):
        if set(vals) - {'date', *TYPED_FIELDS}:
            raise UserError(_("Only the day and the bank totals can be typed on a card control."))
        if any(control.state != 'draft' for control in self):
            raise UserError(_("A validated card control cannot be changed."))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if any(control.state != 'draft' for control in self):
            raise UserError(_("A validated card control cannot be deleted."))

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_validate(self):
        for control in self:
            if control.state != 'draft':
                raise UserError(_("This card control is already validated."))
            if not control.company_id.card_control_journal_ids:
                raise UserError(_("Choose the card journals in the Sales settings first."))
            total_odoo = control._odoo_card_total()
            matched = control.currency_id.is_zero(control.total_files - total_odoo)
            # super().write: state and the frozen values are refused by write() on purpose.
            super(CardControl, control).write({
                'state': 'matched' if matched else 'to_check',
                'validated_total_odoo': total_odoo,
                'user_id': self.env.uid,
                'validated_at': fields.Datetime.now(),
            })
        return True

    def action_view_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Card Payments"),
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': self._card_payment_domain(),
            'context': {'create': False},
        }
