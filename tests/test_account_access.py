import account_access


class Adapter:
    def __init__(self, user=None, access=None, error=None):
        self.user = user or {}
        self.value = access or {}
        self.error = error

    def current_user(self):
        return self.user

    def access(self):
        if self.error:
            raise self.error
        return self.value


def test_bootstrap_owner_is_always_admin_even_when_rpc_says_no():
    result = account_access.current_access(Adapter(
        {"id": "owner", "email": "Nathan@Servpro10100.com"},
        {"is_admin": False, "departments": ["ie"]}))
    assert result["is_owner"] is True
    assert result["is_admin"] is True
    assert result["departments"] == ["IE"]


def test_rpc_admin_is_normalized_for_regular_user():
    result = account_access.current_access(Adapter(
        {"id": "sam", "email": "samantha@servpro10100.com"},
        {"is_admin": True, "departments": ["ie", "IE", "oc"]}))
    assert result["is_owner"] is False
    assert result["is_admin"] is True
    assert result["departments"] == ["IE", "OC"]


def test_identity_survives_temporary_access_failure():
    result = account_access.current_access(Adapter(
        {"id": "sam", "email": "samantha@servpro10100.com"},
        error=RuntimeError("offline")))
    assert result["signed_in"] is True
    assert result["is_admin"] is False
    assert "offline" in result["error"]
