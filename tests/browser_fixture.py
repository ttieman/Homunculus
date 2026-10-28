"""CI-only synthetic observations linked to generated test-pattern video."""
import hashlib
import json
from pathlib import Path
from test_spatial import bundle

if __name__=='__main__':
    data=bundle()
    data['provenance']['video_sha256']=hashlib.sha256(Path('outputs/browser-fixture.webm').read_bytes()).hexdigest()
    Path('outputs/browser-fixture.json').write_text(json.dumps(data),encoding='utf-8')
