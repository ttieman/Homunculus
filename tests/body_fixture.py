"""CI-only: a synthetic full-body capture (test rig posed over time) for the browser test."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from homunculus.retarget.character import Rig  # noqa: E402
from character_fixture import build  # noqa: E402
from test_body import synthetic_capture  # noqa: E402

if __name__ == '__main__':
    out = Path(sys.argv[1] if len(sys.argv) > 1 else 'outputs/test-body-capture.json')
    out.parent.mkdir(exist_ok=True)
    capture, _ = synthetic_capture(Rig(build()), seconds=6)
    out.write_text(json.dumps(capture), encoding='utf-8')
    print(out)
