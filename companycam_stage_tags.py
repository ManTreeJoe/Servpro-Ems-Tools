"""Canonical additive tags for stages explicitly selected in the pull preview."""

STAGE_TAGS = {
    'Initial': 'Initial Inspection',
    'Demo': 'Demo',
    'Monitor': 'Monitor',
    'Abatement Prep': 'Abatement Prep',
    'Mold Prep': 'Mold Prep',
    'Reinspection': 'Reinspection',
    'Contents': 'Contents',
    'Scope': 'Scope',
    'Post': 'Post',
    'Cleaning': 'Cleaning',
}


def stage_tag(stage):
    name = str(stage or '').strip().casefold()
    return next((tag for key, tag in STAGE_TAGS.items() if key.casefold() == name), '')


def approved_stage_tags():
    """Resolve only existing catalog names; never create a guessed tag."""
    import companycam_api as cc
    names = {}
    for page in range(1, 21):
        rows = cc._call('/tags', params={'page': page, 'per_page': 100}, _max_retries=0)
        if not isinstance(rows, list):
            raise ValueError('CompanyCam tag list could not be verified')
        for row in rows:
            name = str(row.get('display_value') or row.get('value') or '').strip()
            if name:
                names[name.casefold()] = name
        if len(rows) < 100:
            return {stage: names[tag.casefold()] for stage, tag in STAGE_TAGS.items()
                    if tag.casefold() in names}
    raise ValueError('CompanyCam tag list is incomplete')
