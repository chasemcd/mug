"""
Admin routes for MUG dashboard.

Provides:
- /admin/ - Main dashboard (requires authentication)
- /admin/login - Login page and authentication
- /admin/logout - Session logout
"""
from __future__ import annotations

import functools
import os

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from . import AdminUser, admin_bp

# Admin password from environment variable (default for development)
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')


def admin_required(f):
    """Decorator that requires admin authentication."""
    @functools.wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/')
@admin_required
def dashboard():
    """Main admin dashboard page."""
    return render_template('dashboard.html')


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Admin login page."""
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))

    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == ADMIN_PASSWORD:
            user = AdminUser()
            login_user(user, remember=True)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('admin.dashboard'))
        else:
            error = 'Invalid password'

    return render_template('login.html', error=error)


@admin_bp.route('/logout')
@login_required
def logout():
    """Log out admin user."""
    logout_user()
    return redirect(url_for('admin.login'))
