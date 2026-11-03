"""Launch only the Headless Shell revision required by installed Playwright."""
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess


def browser_metadata():
    import playwright

    package = Path(playwright.__file__).resolve().parent / 'driver' / 'package'
    manifest_path = package / 'browsers.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    matches = [row for row in manifest['browsers'] if row['name'] == 'chromium-headless-shell']
    if len(matches) != 1:
        raise RuntimeError('Installed Playwright does not declare one Chromium Headless Shell')
    declared = matches[0]
    # Ask the installed driver's registry to resolve its own platform, revision
    # override, registry location and executable layout. Never glob for a browser.
    registry_modules = [package / 'lib/coreBundle.js', package / 'lib/server/registry/index.js']
    registry = next((path for path in registry_modules if path.is_file()), None)
    node = package.parent / ('node.exe' if os.name == 'nt' else 'node')
    if registry is None or not node.is_file():
        raise RuntimeError('Installed Playwright bundled driver registry is unavailable')
    probe = '''
const module = require(process.argv[1]);
const registry = module.registry && (module.registry.registry || module.registry);
if (!registry) throw new Error('Installed driver does not export its browser registry');
const executable = registry.findExecutable('chromium-headless-shell');
if (!executable) throw new Error('Installed driver has no Headless Shell executable');
process.stdout.write(JSON.stringify({path: executable.executablePath(), directory: executable.directory}));
'''
    result = subprocess.run([str(node), '-e', probe, str(registry)], capture_output=True,
                            text=True, encoding='utf8', timeout=15, check=False)
    if result.returncode:
        raise RuntimeError('Installed Playwright registry probe failed: ' + result.stderr.strip()[:1000])
    resolved = json.loads(result.stdout)
    executable = Path(resolved['path']).absolute()
    directory = Path(resolved['directory']).absolute()
    base_prefix = 'chromium_headless_shell'
    valid_directories = {base_prefix + '-' + str(declared['revision']): str(declared['revision'])}
    for host, revision in declared.get('revisionOverrides', {}).items():
        prefix = (base_prefix + '_' + host + '_special').replace('-', '_')
        valid_directories[prefix + '-' + str(revision)] = str(revision)
    if directory.name not in valid_directories:
        raise RuntimeError('Headless Shell directory does not match installed browsers.json revision')
    if (executable.name not in ('chrome-headless-shell', 'chrome-headless-shell.exe')
            or not executable.is_relative_to(directory)):
        raise RuntimeError('Installed registry resolved an unexpected Headless Shell executable')
    if not executable.is_file():
        raise RuntimeError('Matching Playwright Headless Shell is missing: ' + str(executable))
    # Resolve symlinks only after enforcing the driver-selected logical path.
    return {'playwright_version': importlib.metadata.version('playwright'),
            'browsers_manifest': str(manifest_path),
            'browsers_manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'revision': valid_directories[directory.name],
            'expected_browser_version': declared.get('browserVersion'),
            'executable': str(executable),
            'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'registry_directory': str(directory),
            'runtime': 'bundled Chromium Headless Shell',
            'personal_profile': False, 'system_browser_fallback': False}


def launch_browser(playwright, *, timeout=30000):
    """Return (browser, provenance); no channel/profile/executable override."""
    metadata = browser_metadata()
    browser = playwright.chromium.launch(executable_path=metadata['executable'],
                                        headless=True, timeout=timeout)
    actual_version = browser.version
    metadata['actual_browser_version'] = actual_version
    expected = metadata.get('expected_browser_version')
    if expected and actual_version != expected:
        browser.close()
        raise RuntimeError('Headless Shell version differs from installed Playwright: '
                           + actual_version + ' != ' + expected)
    return browser, metadata


@contextmanager
def report_browser():
    """Fresh disposable browser and context; closes both even on verification failure."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, metadata = launch_browser(playwright)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000},
                                      device_scale_factor=1, color_scheme='light',
                                      accept_downloads=False, service_workers='block')
        try:
            yield context, metadata
        finally:
            context.close()
            browser.close()


if __name__ == '__main__':
    print(json.dumps(browser_metadata(), ensure_ascii=False, indent=2))
