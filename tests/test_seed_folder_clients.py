from tools.seed_folder_clients import choose, name_key


def test_folder_parent_and_conflicts(tmp_path):
    root = tmp_path / '2026 Jobs'
    a = root / 'Customer A' / '2nd Claim'
    b = root / 'Customer B'
    a.mkdir(parents=True)
    b.mkdir()
    folders = {name_key(n): n for n in ['Customer A', 'Customer B']}
    job = dict(display_name='Different job title', client_id=None, client_revision=0)
    assert choose(job, [str(a)], str(root), folders) == ('Customer A', 'saved folder link')
    assert choose(job, [str(a), str(b)], str(root), folders)[1] == 'conflicting folder links'
    assert choose(dict(job, client_id='manual'), [str(a)], str(root), folders)[0] is None
    assert choose(dict(job, client_revision=2), [str(a)], str(root), folders)[0] is None


def test_no_fuzzy_or_outside_root(tmp_path):
    root = tmp_path / '2026 Jobs'
    (root / 'Customer 12').mkdir(parents=True)
    outside = tmp_path / 'Other' / 'Customer 12'
    outside.mkdir(parents=True)
    folders = {'customer 12': 'Customer 12'}
    job = dict(display_name='Customer 12', client_id=None, client_revision=0)
    assert choose(job, [], str(root), folders)[0] == 'Customer 12'
    assert choose(job, [str(outside)], str(root), folders)[0] is None
    assert choose(dict(job, display_name='Customer 13'), [], str(root), folders)[0] is None
