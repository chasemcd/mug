"""
Admin module for Interactive Gym experiment monitoring dashboard.

Provides:
- Flask Blueprint for /admin routes
- AdminUser class for Flask-Login session management
- Admin namespace for real-time SocketIO updates
"""
from flask import Blueprint
from flask_login import LoginManager

admin_bp = Blueprint(
    'admin',
    __name__,
    url_prefix='/admin',
    template_folder='templates',
    static_folder='static',
    static_url_path='/admin/static'
)


class AdminUser:
    """
    Simple admin user class for Flask-Login.

    Single-user authentication - no multi-user permissions needed for v1.1.
    """

    def __init__(self, id='admin'):
        self.id = id
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False

    def get_id(self):
        return self.id


from . import routes  # Import routes after blueprint creation
