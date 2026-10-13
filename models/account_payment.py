from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .cash_control_day import VALIDATED_PAYMENT_STATES


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    cash_day_id = fields.Many2one(
        'cash.control.day', string="Cash Day", readonly=True, copy=False,
        index='btree_not_null', ondelete='restrict')

    # Posting is a write of `state` (action_post, the register wizard's create and a raw RPC
    # write all end there), so the link is made on the state transition, not in action_post.

    @api.model_create_multi
    def create(self, vals_list):
        if any('cash_day_id' in vals for vals in vals_list):
            raise UserError(_("The cash day of a payment is set by the system."))
        payments = super().create(vals_list)
        payments.filtered(
            lambda p: p.state in VALIDATED_PAYMENT_STATES and not p.cash_day_id
        )._cash_control_attach_day()
        return payments

    def write(self, vals):
        if 'cash_day_id' in vals:
            raise UserError(_("The cash day of a payment is set by the system."))
        becoming_valid = (
            self.filtered(lambda p: p.state not in VALIDATED_PAYMENT_STATES)
            if 'state' in vals else self.browse()
        )
        res = super().write(vals)
        becoming_valid.filtered(lambda p: p.state in VALIDATED_PAYMENT_STATES)._cash_control_attach_day()
        return res

    def _cash_control_attach_day(self):
        """Link cash payments to the open cash day; refuse them when no day is open.
        A payment re-validated later moves to the day open at that time."""
        for company, payments in self.grouped('company_id').items():
            journal = company.cash_control_journal_id
            payments = payments.filtered(lambda p: p.journal_id == journal)
            if not payments:
                continue
            # sudo: the link is a system rule; the user posting may not see the open day
            # (record rules) or may have no Sales group at all.
            day = self.env['cash.control.day'].sudo()._open_day(company)
            if not day:
                raise UserError(_(
                    "No cash day is open for %(journal)s. Open the cash day before recording a cash payment.",
                    journal=journal.display_name,
                ))
            # super(): write() refuses cash_day_id from any caller on purpose.
            super(AccountPayment, payments).write({'cash_day_id': day.id})
