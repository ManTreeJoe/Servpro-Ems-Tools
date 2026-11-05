"""Read-only management details belonging to the exact opened Trello card.

Do not write these into shared customer facts: divisions can have different
work-order contacts. Keep unknown roles as written rather than inferring them.
"""
import re


def fields(description):
    section = ''
    contact = 0
    result = []
    extra = []
    labels = {
        'PROPERTY MANAGER COMPANY': ('management_company', 'Management company'),
        'MANAGEMENT COMPANY': ('management_company', 'Management company'),
        'HOA PROPERTY MANAGER COMPANY': ('hoa_management_company', 'HOA management company'),
        'INDIVIDUAL PROPERTY MANAGER COMPANY': ('individual_management_company', 'Individual management company'),
        'WORK ORDER NUMBER': ('work_order_number', 'Work order'),
        'PROPERTY / SITE': ('property_site', 'Property / site'),
        'PORTAL LINK': ('management_portal', 'Portal'),
        'LOSS LOCATION': ('loss_location', 'Loss location'),
    }
    for raw in (description or '').splitlines():
        line = re.sub(r'^#{1,6}\s*', '', raw.strip()).replace('**', '')
        if line.upper() in ('ACCOUNT INFO', 'CUSTOMER INFORMATION', 'LINKS',
                            'TENANT INFORMATION', 'INSURANCE INFORMATION',
                            'PROPERTY DETAILS', 'NOTES', 'SCOPE OF WORK'):
            section = line.upper()
            continue
        if line == '---':
            section = ''
        if section not in ('ACCOUNT INFO', 'CUSTOMER INFORMATION', 'LINKS'):
            continue
        pair = re.match(r'([^:]+):\s*(.*)', line)
        fid = label = value = ''
        if pair:
            key, value = pair[1].strip().upper(), pair[2].strip()
            if key in labels:
                fid, label = labels[key]
            elif section == 'ACCOUNT INFO' and key.startswith('POINT OF CONTACT '):
                kind = key.removeprefix('POINT OF CONTACT ')
                if kind == 'NAME':
                    contact += 1
                if contact and kind in ('NAME', 'NUMBER', 'EMAIL'):
                    fid = f'management_contact_{contact}_{kind.lower()}'
                    label = f'Management contact {contact} · {kind.title()}'
        gate = re.fullmatch(r'Gate code\s*:?\s+(.+)', line, re.I)
        if gate:
            fid, label, value = 'gate_code', 'Gate code', gate[1]
        if section == 'ACCOUNT INFO' and line and not fid:
            # Keep free-form/legacy account contacts verbatim, not assigned to
            # the previous person merely because they appear on the next line.
            if not pair or pair[2].strip():
                extra.append(line)
        elif section == 'CUSTOMER INFORMATION' and line and not fid:
            standard = {'CUSTOMER NAME', 'ADDRESS', 'PHONE NUMBER', 'EMAIL',
                        'SOURCE OF LEAD', 'ADDITIONAL CONTACTS'}
            if not pair or (pair[1].strip().upper() not in standard and pair[2].strip()):
                extra.append(line)
        if fid and value:
            # Preserve readable labels, without Markdown/mailto decorations.
            value = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', value)
            result.append({'id': fid, 'label': label, 'value': value, 'core': False})
    if extra:
        result.append({'id': 'management_account_details', 'label': 'Additional contact / account details',
                       'value': '\n'.join(extra), 'core': False})
    return result
