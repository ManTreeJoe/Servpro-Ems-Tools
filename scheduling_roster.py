"""Approved IE scheduling people, not authentication or notification identities.

Keep this separate from photo-folder technician aliases: merging scheduling
names must not rename folders, rewrite historical visits, or grant access.
The current schedule contract stores display names; account linking is deferred.
"""

# Nathan confirmed the roster and these aliases on 2026-10-07.
IE_PEOPLE = (
    ('Aaron P', ('Aaron', 'AP')),
    ('Brenda', ()), ('Cesar', ()), ('Danny', ()), ('Edwin', ()),
    ('Elena', ()), ('Fernando', ('FB',)), ('George', ('GL',)),
    ('Jesse', ()), ('Johnny', ('JL',)),
    ('Jose Diaz', ('Jose',)), ('Jose Manuel', ('Jose M',)),
    ('Juan', ('Juan M',)), ('Marco', ()), ('Maria', ()),
    ('Maricruz', ('M.Cruz', 'Cruz')),
    ('Mario Nevarez', ('Mario N', 'Nevarez')),
    ('Mark E', ('ME',)), ('Mark L', ('ML',)), ('Melvin', ()),
    ('Mike', ()), ('Nestor', ()), ('Pablo', ('PG',)), ('PCB', ()),
    ('Priscilla', ()), ('Rafa', ()), ('Robert', ()), ('Rudy', ('RQ',)),
    ('Sam', ()), ('Sergio', ()), ('Uli', ()),
    ('Vince', ('Vicente',)), ('Wendy', ()),
)


def entries(department, local_roster):
    """Return detached picker entries; retain local additions, dedupe aliases.

Approved aliases win conflicting legacy mappings, but only for IE scheduling.
Other offices continue to use their existing configured tech list.
"""
    people = IE_PEOPLE if department == 'IE' else ()
    result = {name: set(aliases) for name, aliases in people}
    owners = {token.casefold(): name for name, aliases in people
              for token in (name, *aliases)}
    for name in local_roster.get('names') or []:
        name = str(name).strip()
        if not name:
            continue
        canonical = owners.setdefault(name.casefold(), name)
        result.setdefault(canonical, set())
    for alias, target in (local_roster.get('abbrev') or {}).items():
        alias, target = str(alias).strip(), str(target).strip()
        canonical = owners.get(target.casefold())
        if not alias or canonical is None:
            continue
        owner = owners.get(alias.casefold())
        if owner is not None and owner != canonical:
            continue
        owners[alias.casefold()] = canonical
        if alias.casefold() != canonical.casefold():
            result[canonical].add(alias)
    return [{'name': name, 'aliases': sorted(aliases, key=str.casefold)}
            for name, aliases in sorted(result.items(), key=lambda row: row[0].casefold())]
