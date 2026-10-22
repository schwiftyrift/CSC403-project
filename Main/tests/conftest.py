import pytest
from service.mailer import SETTINGS

@pytest.fixture(autouse=True)
def no_real_email(monkeypatch):
    # Tests must never send real email, even on a machine with SMTP settings in its environment.
    for name in (*SETTINGS, "PUBLIC_ORIGIN"):
        monkeypatch.delenv(name, raising=False)
