import os
import tempfile

# Keep test runs away from the user's real data folder.
os.environ.setdefault("CLIPFOUNDRY_DATA", tempfile.mkdtemp(prefix="clipfoundry-test-"))
# The app starts no autopilot worker process in tests; autopilot tests run a worker host in threads themselves.
os.environ.setdefault("CLIPFOUNDRY_WORKERS", "off")
