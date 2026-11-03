"""Build and export local Docker images without a registry or context switch."""
import argparse
import datetime
import hashlib
import fnmatch
import json
from pathlib import Path
import subprocess


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def source_digest(folder):
    """Record a reproducible checksum of source files, excluding local state."""
    value = hashlib.sha256()
    patterns = ['__pycache__', '*.pyc', '.env', '*.sqlite3*']
    if folder.name == 'backend':
        patterns.append('storage')
    for path in sorted(folder.rglob('*')):
        relative = path.relative_to(folder)
        if not path.is_file() or any(fnmatch.fnmatch(part, pattern) for part in relative.parts for pattern in patterns):
            continue
        value.update(relative.as_posix().encode('utf-8') + b'\0' + digest(path).encode('ascii') + b'\n')
    return value.hexdigest()


def export(destination, context, tag, include_dind=False, lab_dockerfile='Dockerfile', reuse_lab_image=None, extra_images=()):
    root = Path(__file__).resolve().parents[1]
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / 'opsforge-images.tar'
    manifest = destination / 'local-images.json'
    if archive.exists() or manifest.exists():
        raise ValueError('Output already exists; choose a new directory')
    docker = ['docker', '--context', context] if context else ['docker']
    images = {}
    for part in ('backend', 'frontend', 'lab'):
        image = 'opsforge-' + part + ':' + tag
        source_before = source_digest(root / part)
        dockerfile = root / part / (lab_dockerfile if part == 'lab' else 'Dockerfile')
        if part == 'lab' and reuse_lab_image:
            # Preserve the immutable image actually used by native validation.
            existing=json.loads(subprocess.check_output([*docker,'image','inspect',reuse_lab_image],text=True))[0]
            if existing['Os']!='linux' or existing['Config'].get('User')!='1000:1000':
                raise ValueError('Reused lab must be the explicit non-root Linux lab image')
            subprocess.run([*docker,'tag',existing['Id'],image],check=True)
        else:
            subprocess.run([*docker, 'build', '-f', str(dockerfile), '-t', image, str(root / part)], check=True)
        if source_before != source_digest(root / part):
            raise RuntimeError('Source changed while building ' + part + '; rerun after edits finish')
        info = json.loads(subprocess.check_output([*docker, 'image', 'inspect', image], text=True))[0]
        images[part] = {'tag': image, 'id': info['Id'], 'architecture': info['Architecture'],
                        'os': info['Os'], 'bytes': info['Size'], 'source_sha256': source_before,
                        'dockerfile': dockerfile.relative_to(root).as_posix()}
        if part=='lab' and reuse_lab_image:
            images[part].update(reused_image=reuse_lab_image,source_built_in_this_export=False)
    if include_dind:
        image = 'docker:27-dind'
        info = json.loads(subprocess.check_output([*docker, 'image', 'inspect', image], text=True))[0]
        images['dind'] = {'tag': image, 'id': info['Id'], 'architecture': info['Architecture'],
                          'os': info['Os'], 'bytes': info['Size']}
    for index, image in enumerate(extra_images):
        info=json.loads(subprocess.check_output([*docker,'image','inspect',image],text=True))[0]
        images['validation_environment_'+str(index)]={'tag':image,'id':info['Id'],'architecture':info['Architecture'],
            'os':info['Os'],'bytes':info['Size'],'scope':'Exact native validation or private-sidecar environment; separate from default workspace image'}
    subprocess.run([*docker, 'save', '-o', str(archive), *[v['tag'] for v in images.values()]], check=True)
    payload = {'format': 'opsforge-local-images-v1',
               'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'images': images,
               'archive': {'file': archive.name, 'bytes': archive.stat().st_size, 'sha256': digest(archive)},
               'scope': 'local images; not a pushed registry release or external deployment'}
    manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Local image archive:', archive)
    print('Manifest:', manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    parser.add_argument('--context', default='', help='Explicit Docker context; default remains unchanged')
    parser.add_argument('--tag', default='20261025-local')
    parser.add_argument('--include-dind', action='store_true', help='Also export the already-pulled docker:27-dind image for dedicated Docker workspaces')
    parser.add_argument('--lab-dockerfile', choices=['Dockerfile', 'Dockerfile.pilot', 'Dockerfile.controllers','Dockerfile.native-next','Dockerfile.br'], default='Dockerfile',
                        help='explicitly select the native Kafka/TiDB extension for pilot images')
    parser.add_argument('--reuse-lab-image',help='Retag and export this exact previously validated local lab image instead of rebuilding it')
    parser.add_argument('--include-validation-image',action='append',default=[],help='Also save this exact existing validation/sidecar image without rebuilding or changing its tag')
    args = parser.parse_args()
    export(args.destination, args.context, args.tag, args.include_dind, args.lab_dockerfile,args.reuse_lab_image,args.include_validation_image)
