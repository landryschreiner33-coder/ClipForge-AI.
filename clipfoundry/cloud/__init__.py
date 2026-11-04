"""ClipForge cloud mode: owner sign-in, workspaces, request authorization and deployment checks.

Desktop (local) mode is the default and is unchanged by this package: nothing here runs unless
``CLIPFOUNDRY_MODE=cloud`` is set, and cloud mode refuses to start while any required protection is missing.
"""
