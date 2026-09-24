import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def administrator(client):
    user = User.objects.create_user(username="admin", is_staff=True)
    user.groups.add(Group.objects.get(name="Admin"))
    client.force_login(user)
    return user


@pytest.mark.parametrize(
    ("route", "status"),
    [
        # Superusers are hidden from non-superuser Admins, so the admin treats them as missing.
        ("admin:auth_user_change", 302),
        ("admin:auth_user_delete", 302),
        ("admin:auth_user_password_change", 404),
    ],
)
def test_admin_cannot_edit_delete_or_reset_superuser(client, administrator, route, status):
    superuser = User.objects.create_superuser(username="root", password="secret")
    response = client.post(
        reverse(route, args=[superuser.pk]),
        {"password1": "attacker123!", "password2": "attacker123!", "post": "yes"},
    )
    assert response.status_code == status
    superuser.refresh_from_db()
    assert superuser.check_password("secret")


def test_admin_cannot_grant_superuser_or_direct_permissions(client, administrator):
    target = User.objects.create_user(username="target", is_staff=True)
    response = client.post(
        reverse("admin:auth_user_change", args=[target.pk]),
        {
            "username": "target",
            "is_active": "on",
            "is_staff": "on",
            "is_superuser": "on",
            "user_permissions": [1],
            "groups": [Group.objects.get(name="Viewer").pk],
        },
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert not target.is_superuser
    assert not target.user_permissions.exists()
    assert list(target.groups.values_list("name", flat=True)) == ["Viewer"]


def test_admin_cannot_modify_group_definitions(client, administrator):
    group = Group.objects.get(name="Agent")
    response = client.post(
        reverse("admin:auth_group_change", args=[group.pk]), {"name": "Agent", "permissions": []}
    )
    assert response.status_code == 403
