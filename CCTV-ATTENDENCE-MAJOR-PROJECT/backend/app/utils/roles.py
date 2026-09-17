"""Centralized role definitions.

Every place in the codebase that needs to know which role strings are
valid should import from here instead of hard-coding role literals, so
the allowed set only has to change in one place.
"""

ROLE_HOD = "hod"
ROLE_FACULTY = "faculty"
ROLE_STUDENT = "student"

ALLOWED_ROLES = (ROLE_HOD, ROLE_FACULTY, ROLE_STUDENT)

# Roles a user may request for themselves via the public /api/auth/register
# endpoint. Both HOD and faculty are deliberately excluded here: an HOD
# account only ever comes from seeding (see utils/seed.py), and a faculty
# account may only be created by an existing HOD through the
# HOD-protected /api/admin/faculty endpoints. Public registration can
# create a student account only, and even then never auto-links it to
# any Student profile row - linking is a separate HOD-controlled action.
SELF_REGISTERABLE_ROLES = (ROLE_STUDENT,)


def is_valid_role(role: str) -> bool:
    return role in ALLOWED_ROLES
