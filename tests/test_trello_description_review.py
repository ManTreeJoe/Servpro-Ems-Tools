from trello_description_review import review, for_card


def test_keeps_unknown_and_duplicate_lines_with_original():
    text = ('**CUSTOMER INFORMATION**\nCustomer Name: Example\n'
            'Phone Number: 555-0100\nPhone Number: 555-0101\n'
            'Access instructions: Call first\n')
    result = review(text)
    assert result['original'] == text
    assert 'Phone Number: 555-0100' in result['additional']
    assert 'Phone Number: 555-0101' in result['additional']
    assert 'Access instructions: Call first' in result['additional']
    assert any(f['id'] == 'customer_name' and f['value'] == 'Example' for f in result['suggestions'])


def test_unstructured_and_multiline_remain_visible():
    text = 'CUSTOMER INFORMATION\nCustomer Name: Example\n\n**SCOPE OF WORK**\nINITIAL: Kitchen\nDownstairs: hallway'
    result = review(text)
    assert 'Customer Name: Example' in result['additional']
    assert 'Downstairs: hallway' in result['additional']
    assert result['original'] == text


def test_empty_description_is_distinct_from_not_loaded():
    assert review('') == {'original': '', 'additional': '', 'suggestions': []}


def test_never_returns_another_cards_description():
    assert for_card({'id': 'other', 'desc': 'private details'}, 'selected') == {}
    assert for_card({'id': 'selected'}, 'selected') == {}
    assert for_card({'id': 'selected', 'desc': ''}, 'selected')['description_review']['original'] == ''
