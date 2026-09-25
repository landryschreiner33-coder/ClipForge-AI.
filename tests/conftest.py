import os
import tempfile

# Keep test runs away from the user's real data folder.
os.environ.setdefault("CLIPFOUNDRY_DATA", tempfile.mkdtemp(prefix="clipfoundry-test-"))
