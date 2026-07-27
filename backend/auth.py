from flask_login import LoginManager, UserMixin

from models import Staff

login_manager = LoginManager()
login_manager.login_view = "staff_login_form"


class StaffUser(UserMixin):
    """Thin flask-login wrapper around the Staff model."""

    def __init__(self, staff: Staff):
        self.staff = staff
        self.id = str(staff.id)

    def __getattr__(self, item):
        return getattr(self.staff, item)


@login_manager.user_loader
def load_user(staff_id):
    staff = Staff.query.get(int(staff_id))
    return StaffUser(staff) if staff else None
