from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cash_reference_float = fields.Monetary(
        related='company_id.cash_reference_float', readonly=False)
    cash_control_journal_id = fields.Many2one(
        related='company_id.cash_control_journal_id', readonly=False)
    card_control_journal_ids = fields.Many2many(
        related='company_id.card_control_journal_ids', readonly=False)
    card_control_method_line_ids = fields.Many2many(
        related='company_id.card_control_method_line_ids', readonly=False)
