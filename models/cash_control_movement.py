from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CashControlMovement(models.Model):
    _name = 'cash.control.movement'
    _description = "Cash In / Out"
    _order = 'id desc'

    day_id = fields.Many2one(
        'cash.control.day', string="Cash Day", required=True, readonly=True,
        index=True, ondelete='restrict')
    company_id = fields.Many2one(related='day_id.company_id', store=True)
    currency_id = fields.Many2one(related='day_id.currency_id')
    type = fields.Selection([('in', "Cash In"), ('out', "Cash Out")], required=True, default='out')
    amount = fields.Monetary(required=True)
    reason = fields.Char(required=True)
    user_id = fields.Many2one('res.users', string="Recorded By", readonly=True)

    _amount_positive = models.Constraint('CHECK(amount > 0)', "The amount must be positive.")

    @api.model_create_multi
    def create(self, vals_list):
        day = self.env['cash.control.day']._open_day(self.env.company)
        if not day:
            raise UserError(_("No cash day is open. Open the cash day first."))
        # Only type, amount and reason come from the client; the day and the user are the server's.
        return super().create([
            {
                **{key: vals[key] for key in ('type', 'amount', 'reason') if key in vals},
                'day_id': day.id,
                'user_id': self.env.uid,
            }
            for vals in vals_list
        ])

    def write(self, vals):
        raise UserError(_("A cash movement cannot be changed once recorded."))

    @api.ondelete(at_uninstall=False)
    def _unlink_never(self):
        raise UserError(_("Cash movements cannot be deleted."))
