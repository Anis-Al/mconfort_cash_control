from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_amount

from ..models.cash_control_day import CONTROLLER_GROUP


class CashControlDayWizard(models.TransientModel):
    """'My Cash Day' pop-up: open the day, record cash in/out, count and close.

    Every write goes through cash.control.day / cash.control.movement, so their locks apply.
    The day is never stored here: it is always the open day of the company, computed.
    """
    _name = 'cash.control.day.wizard'
    _description = "My Cash Day"

    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id, readonly=True)
    day_id = fields.Many2one('cash.control.day', compute='_compute_day_id')

    # Opening
    opening_amount = fields.Monetary(
        default=lambda self: self.env['cash.control.day']._last_closed_day().counted_amount)
    can_edit_opening = fields.Boolean(compute='_compute_day_id')

    # The open day (read-only mirrors)
    day_name = fields.Char(related='day_id.name')
    theoretical_amount = fields.Monetary(related='day_id.theoretical_amount')
    day_opening_amount = fields.Monetary(related='day_id.opening_amount', string="Opening")
    payment_in_amount = fields.Monetary(related='day_id.payment_in_amount')
    payment_out_amount = fields.Monetary(related='day_id.payment_out_amount')
    movement_in_amount = fields.Monetary(related='day_id.movement_in_amount')
    movement_out_amount = fields.Monetary(related='day_id.movement_out_amount')
    deposit_amount = fields.Monetary(related='day_id.deposit_amount')

    # Count
    counted_amount = fields.Monetary()
    closing_note = fields.Text()
    count_gap = fields.Monetary(string="Gap", compute='_compute_count_gap')

    # Cash in / out
    movement_type = fields.Selection([('in', "Cash In"), ('out', "Cash Out")], default='out')
    movement_amount = fields.Monetary(string="Amount")
    movement_reason = fields.Char(string="Reason")

    @api.depends_context('uid', 'allowed_company_ids')
    def _compute_day_id(self):
        Day = self.env['cash.control.day']
        day = Day._open_day(self.env.company)
        first_opening = self.env.user.has_group(CONTROLLER_GROUP) and not Day._last_closed_day()
        for wizard in self:
            wizard.day_id = day
            wizard.can_edit_opening = first_opening

    @api.depends('counted_amount', 'day_id')
    def _compute_count_gap(self):
        for wizard in self:
            wizard.count_gap = wizard.counted_amount - wizard.day_id.theoretical_amount

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    @api.model
    def action_open_wizard(self):
        return self.create({})._reopen()

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("My Cash Day"),
            'res_model': self._name,
            'res_id': self.id,
            'views': [(False, 'form')],
            'target': 'new',
        }

    def action_open_day(self):
        self.ensure_one()
        self.env['cash.control.day'].create({'opening_amount': self.opening_amount})
        return self._reopen()

    def action_add_movement(self):
        self.ensure_one()
        if self.movement_amount <= 0 or not (self.movement_reason or '').strip():
            raise UserError(_("Type a positive amount and a reason."))
        self.env['cash.control.movement'].create({
            'type': self.movement_type, 'amount': self.movement_amount, 'reason': self.movement_reason,
        })
        self.write({'movement_amount': 0.0, 'movement_reason': False})
        return self._reopen()

    def action_close_day(self):
        self.ensure_one()
        day = self.day_id
        if not day:
            raise UserError(_("No cash day is open."))
        day.write({'counted_amount': self.counted_amount, 'closing_note': self.closing_note})
        day.action_close()
        matched = day.currency_id.is_zero(day.difference)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("%(day)s closed", day=day.name),
                'message': _("Difference: %(gap)s", gap=format_amount(self.env, day.difference, day.currency_id)),
                'type': 'success' if matched else 'warning',
                'sticky': not matched,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_view_day(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'cash.control.day',
            'res_id': self.day_id.id,
            'views': [(False, 'form')],
            'target': 'current',
        }
