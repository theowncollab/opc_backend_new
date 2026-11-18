"""
OPC team roles and what each may do. Mirrors dashboard-app/src/admin/permissions.ts
(that copy only hides buttons; this one is the real check). Keep the two in sync.
"""
ALL = [
    'people.view', 'people.edit', 'people.suspend', 'verification.decide', 'deals.view', 'deals.manage',
    'disputes.resolve', 'moderation.act', 'payouts.release', 'meetings.manage',
    'support.reply', 'team.manage', 'audit.view',
]

ROLE_PERMISSIONS = {
    'Owner': ALL,
    'Operations': ['people.view', 'people.edit', 'people.suspend', 'verification.decide', 'deals.view', 'deals.manage',
                   'disputes.resolve', 'meetings.manage', 'support.reply', 'audit.view'],
    'Finance': ['people.view', 'deals.view', 'disputes.resolve', 'payouts.release', 'audit.view'],
    'Support': ['people.view', 'deals.view', 'meetings.manage', 'support.reply'],
    'Moderator': ['people.view', 'people.suspend', 'moderation.act', 'support.reply'],
}

TEAM_ROLES = list(ROLE_PERMISSIONS)


def can(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, [])
