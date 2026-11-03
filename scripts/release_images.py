"""Build once, deploy the exact pushed image digests, including on rollback."""
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid


def build(registry, destination):
    if not re.fullmatch(r'[A-Za-z0-9._:/-]+', registry):
        raise ValueError('Invalid registry')
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Release manifest already exists; choose a new path')
    root = Path(__file__).resolve().parents[1]
    tag = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
    images = {}
    for part in ('backend', 'frontend', 'lab'):
        repository = registry.rstrip('/') + '/opsforge-' + part
        image = repository + ':' + tag
        subprocess.run(['docker', 'build', '-t', image, str(root / part)], check=True)
        subprocess.run(['docker', 'push', image], check=True)
        digests = json.loads(subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{json .RepoDigests}}', image], text=True))
        images[part] = next(d for d in digests if re.fullmatch(re.escape(repository) + r'@sha256:[a-f0-9]{64}', d))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8') as f:
        json.dump({'tag': tag, 'images': images}, f, indent=2)
    print('Release manifest:', destination.resolve())


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2])
