import pytest
from django.contrib.auth.models import Group, User

pytestmark = pytest.mark.django_db


def test_roles_are_created_by_migrations():
    assert set(Group.objects.values_list("name", flat=True)) == {"Admin", "Agent", "Viewer"}


@pytest.mark.parametrize(
    "role,allowed,denied",
    [
        (
            "Agent",
            {"add_ticket", "change_ticket", "add_comment", "change_comment", "add_customer"},
            {"delete_ticket", "change_customer", "delete_customer", "change_user", "change_group"},
        ),
        (
            "Viewer",
            {"view_ticket", "view_comment", "view_customer", "view_agent"},
            {"add_ticket", "change_ticket", "delete_ticket", "add_customer", "change_user"},
        ),
        (
            "Admin",
            {"delete_ticket", "change_customer", "add_agent", "change_user"},
            {"add_group", "change_group", "delete_group", "add_permission", "change_permission"},
        ),
    ],
)
def test_role_permission_matrix(role, allowed, denied):
    permissions = set(Group.objects.get(name=role).permissions.values_list("codename", flat=True))
    assert allowed <= permissions
    assert permissions.isdisjoint(denied)


def test_staff_flag_alone_grants_no_business_permissions():
    user = User.objects.create_user(username="ungrouped", is_staff=True)
    assert not user.has_perm("tickets.view_ticket")
