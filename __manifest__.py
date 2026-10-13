{
    'name': 'Cash Control',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Cash drawer days, safe deposits and card totals checked by the owner',
    'author': 'Anis Alim',
    'depends': ['account', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'security/cash_control_security.xml',
        'data/ir_sequence_data.xml',
        'views/res_config_settings_views.xml',
        # movement and deposit first: the day form's buttons point at their actions
        'views/cash_control_movement_views.xml',
        'views/cash_safe_deposit_views.xml',
        'views/cash_control_day_views.xml',
        'views/card_control_views.xml',
        'views/cash_control_dashboard_views.xml',
        'wizard/cash_control_day_wizard_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mconfort_cash_control/static/src/dashboard/*',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
